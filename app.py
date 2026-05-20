#!/usr/bin/env python3
"""
DoD Budget Justification Keyword Scout (BudgetPOC Scout)
Full version with Upload button only (no local path)
"""

import os
import re
import json
import time
import shutil
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple, Optional, Any

import streamlit as st
import fitz  # PyMuPDF
import pandas as pd
from whoosh import index as whoosh_index
from whoosh.fields import Schema, TEXT, ID, STORED, KEYWORD
from whoosh.analysis import StemmingAnalyzer, StandardAnalyzer
from whoosh.qparser import MultifieldParser, QueryParser
from whoosh.searching import Results
import webbrowser
from urllib.parse import quote_plus

# ----------------------------- CONFIG -----------------------------
APP_NAME = "DoD Budget Justification Keyword Scout"
INDEX_DIR_NAME = "whoosh_index"
CAPABILITIES_FILE = "my_capabilities.json"
DEFAULT_INDEX_PATH = "./whoosh_index"

DEFAULT_CAPABILITIES = [
    "avionics", "harness", "connector", "electro-mechanical", "electromechanical",
    "MIL-STD", "RDT&E", "payload", "interconnect", "cable assembly", "backshell",
    "wiring", "cabling", "integration", "test equipment", "flight hardware",
    "ground support", "defense manufacturing", "aerospace component"
]

PE_PATTERNS = [
    r'PE\s+(\d{7}[A-Z]?)',
    r'Program Element\s*\(Number/Name\)\s*[:\s]*(\d{7}[A-Z]?)',
    r'R-1 Program Element.*?(\d{7}[A-Z]?)',
    r'Exhibit R-2.*?PE\s+(\d{7}[A-Z]?)',
]

TITLE_PATTERNS = [
    r'PE\s+\d{7}[A-Z]?\s*[:\-]?\s*([A-Za-z][A-Za-z0-9\s\-\(\)]{5,80})',
    r'Program Element.*?[:\-]\s*([A-Za-z][A-Za-z0-9\s\-\(\)]{5,80})',
]

def clean_text(text: str) -> str:
    if not text: return ""
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    for bp in [r'\bUNCLASSIFIED\b', r'\bPage \d+ of \d+\b', r'THIS PAGE INTENTIONALLY LEFT BLANK']:
        text = re.sub(bp, '', text, flags=re.IGNORECASE)
    return text.strip()

def extract_pe_info(text: str) -> Tuple[Optional[str], Optional[str]]:
    pe_number = None
    title = None
    for pattern in PE_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            pe_number = match.group(1).strip().upper()
            break
    if pe_number:
        for tpat in TITLE_PATTERNS:
            tmatch = re.search(tpat, text, re.IGNORECASE)
            if tmatch:
                candidate = tmatch.group(1).strip()
                if len(candidate) > 8 and not candidate.lower().startswith(('pe ', 'program')):
                    title = candidate[:80]
                    break
    return pe_number, title

def process_pdf_to_documents(pdf_path: str) -> List[Dict[str, Any]]:
    documents = []
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        st.error(f"Failed to open {pdf_path}: {e}")
        return documents

    source_name = os.path.basename(pdf_path)
    current_pe = "General Overview"
    current_title = source_name.replace(".pdf", "").replace("_", " ")
    current_text_parts = []
    current_pages = []
    min_chunk_chars = 300

    for page_num in range(len(doc)):
        text = clean_text(doc[page_num].get_text("text"))
        if len(text) < 50: continue
        new_pe, new_title = extract_pe_info(text)
        if new_pe and new_pe != current_pe:
            if current_text_parts and len('\n\n'.join(current_text_parts)) >= min_chunk_chars:
                documents.append({
                    "id": f"{source_name}_{current_pages[0]}_{current_pages[-1]}",
                    "pe_number": current_pe,
                    "program_title": current_title,
                    "source": source_name,
                    "pages": f"{current_pages[0]}-{current_pages[-1]}",
                    "content": "\n\n".join(current_text_parts),
                })
            current_pe = new_pe
            current_title = new_title or current_title
            current_text_parts = [text]
            current_pages = [page_num + 1]
        else:
            current_text_parts.append(text)
            current_pages.append(page_num + 1)

    if current_text_parts and len('\n\n'.join(current_text_parts)) >= min_chunk_chars:
        documents.append({
            "id": f"{source_name}_{current_pages[0]}_{current_pages[-1]}",
            "pe_number": current_pe,
            "program_title": current_title,
            "source": source_name,
            "pages": f"{current_pages[0]}-{current_pages[-1]}",
            "content": "\n\n".join(current_text_parts),
        })
    doc.close()
    return documents

def create_or_open_index(index_path: str):
    schema = Schema(
        id=ID(stored=True, unique=True),
        pe_number=KEYWORD(stored=True),
        program_title=TEXT(stored=True),
        source=TEXT(stored=True),
        pages=STORED(),
        content=TEXT(stored=True, analyzer=StemmingAnalyzer()),
    )
    if not os.path.exists(index_path):
        os.makedirs(index_path, exist_ok=True)
        return whoosh_index.create_in(index_path, schema)
    try:
        return whoosh_index.open_dir(index_path)
    except:
        shutil.rmtree(index_path)
        os.makedirs(index_path, exist_ok=True)
        return whoosh_index.create_in(index_path, schema)

def add_documents_to_index(ix, documents):
    writer = ix.writer()
    for doc in documents:
        writer.update_document(**doc)
    writer.commit()
    return len(documents)

def search_index(ix, query_str, limit=30):
    parser = MultifieldParser(["content", "program_title"], schema=ix.schema)
    q = parser.parse(query_str)
    with ix.searcher() as searcher:
        return searcher.search(q, limit=limit)

def highlight_text(text, keywords, max_chars=600):
    highlighted = text
    for kw in sorted(keywords, key=len, reverse=True):
        if kw:
            highlighted = re.sub(re.escape(kw), f"**{kw}**", highlighted, flags=re.IGNORECASE)
    return highlighted[:max_chars] + ("..." if len(text) > max_chars else "")

def load_capabilities():
    if os.path.exists(CAPABILITIES_FILE):
        try:
            return json.load(open(CAPABILITIES_FILE))["keywords"]
        except:
            pass
    return DEFAULT_CAPABILITIES

def save_capabilities(keywords):
    json.dump({"keywords": keywords}, open(CAPABILITIES_FILE, "w"))

def score_document(content, keywords):
    content_lower = content.lower()
    matched = [kw for kw in keywords if kw.lower() in content_lower]
    return len(matched), matched

def open_search_in_browser(query, engine="google"):
    if engine == "google":
        url = f"https://www.google.com/search?q={quote_plus(query)}"
    elif engine == "linkedin":
        url = f"https://www.linkedin.com/search/results/all/?keywords={quote_plus(query)}"
    elif engine == "sam":
        url = f"https://sam.gov/search/?index=opp&q={quote_plus(query)}&sort=-relevance"
    else:
        url = f"https://www.google.com/search?q={quote_plus(query)}"
    webbrowser.open_new_tab(url)

def build_poc_queries(pe_number, program_title, matched_keywords):
    base = f'"{pe_number}" "{program_title}"' if program_title else f'"{pe_number}"'
    queries = {
        "Google - Program Manager / TPOC": f'{base} ("Program Manager" OR PM OR TPOC OR "Technical Point of Contact" OR "Contracting Officer" OR KO) (Navy OR "Air Force" OR Army OR DARPA OR MDA OR SOCOM)',
        "LinkedIn - Program Leadership": f'{base} ("Program Manager" OR "Technical Director" OR TPOC) (defense OR aerospace)',
        "SBIR / STTR for this PE": f'{pe_number} OR "{program_title}" site:sbir.gov OR site:sttr.gov',
        "Recent Awards": f'{base} OR "{program_title}" (award OR contract) site:usaspending.gov',
        "SAM.gov Opportunities": " ".join(matched_keywords[:4]) + " defense harness OR connector OR avionics",
    }
    return queries

# ----------------------------- STREAMLIT UI -----------------------------
st.set_page_config(page_title=APP_NAME, page_icon="🎯", layout="wide")
st.title("🎯 DoD Budget Justification Keyword Scout")
st.caption("Upload PDFs → Search by keywords → Find POCs • Built for defense contractors")

with st.sidebar:
    st.header("Index Status")
    index_path = st.text_input("Index Location", value=DEFAULT_INDEX_PATH)
    ix = None
    try:
        ix = whoosh_index.open_dir(index_path)
        st.success(f"✅ {ix.searcher().doc_count():,} sections indexed")
    except:
        st.warning("No index yet. Upload PDFs below.")

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📥 Data Ingestion", 
    "🔍 Search & Target", 
    "⭐ My Capabilities", 
    "🧭 POC Research Helper", 
    "ℹ️ Help & About"
])

# ========== TAB 1: DATA INGESTION (UPLOAD ONLY) ==========
with tab1:
    st.header("Ingest & Index Budget Justification PDFs")
    st.markdown("**Upload one or more PDF files** (justification books from comptroller.defense.gov)")

    uploaded_files = st.file_uploader(
        "Upload PDF(s)",
        type=["pdf"],
        accept_multiple_files=True,
        help="You can upload multiple files at once."
    )

    pdf_files_to_process = []
    temp_dir = None

    if uploaded_files:
        import tempfile
        temp_dir = tempfile.mkdtemp()
        for uploaded_file in uploaded_files:
            temp_path = os.path.join(temp_dir, uploaded_file.name)
            with open(temp_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            pdf_files_to_process.append(temp_path)
        st.success(f"✅ {len(uploaded_files)} file(s) ready to process")

    col_a, col_b = st.columns(2)
    with col_a:
        force_rebuild = st.checkbox("Force full rebuild (delete old index)", value=False)
    with col_b:
        max_pdfs = st.number_input("Max PDFs to process (0 = all)", min_value=0, value=0, step=1)

    if st.button("🚀 Scan & Build / Update Index", type="primary", disabled=len(pdf_files_to_process) == 0):
        if max_pdfs > 0:
            pdf_files_to_process = pdf_files_to_process[:max_pdfs]

        if not pdf_files_to_process:
            st.warning("No PDF files to process.")
        else:
            st.info(f"Processing {len(pdf_files_to_process)} PDF(s)...")

            if force_rebuild and os.path.exists(index_path):
                shutil.rmtree(index_path)

            ix = create_or_open_index(index_path)

            progress_bar = st.progress(0.0)
            status_text = st.empty()
            total_docs_added = 0
            start_time = time.time()

            for idx, pdf_path in enumerate(pdf_files_to_process):
                filename = os.path.basename(pdf_path)
                status_text.text(f"Processing ({idx+1}/{len(pdf_files_to_process)}): {filename}")
                docs = process_pdf_to_documents(str(pdf_path))
                added = add_documents_to_index(ix, docs, show_progress=False)
                total_docs_added += added
                progress_bar.progress((idx + 1) / len(pdf_files_to_process))

            elapsed = time.time() - start_time
            status_text.text(f"✅ Done in {elapsed:.1f}s — {total_docs_added:,} sections indexed.")
            st.balloons()
            st.success("Index updated! Go to Search tab.")

            if temp_dir and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)

            st.rerun()

    st.divider()
    st.subheader("What gets indexed?")
    st.markdown("""
    - The tool segments text into **Program Element (PE)** sections.
    - Only substantial descriptive text is kept.
    - Works with both RDT&E and Procurement justification books.
    """)

# ========== TAB 2: SEARCH & TARGET ==========
with tab2:
    st.header("Keyword Search Across Budget Justifications")
    if not ix:
        st.warning("Please upload and index PDFs first.")
    else:
        query = st.text_input("Search keywords", value="harness OR connector OR payload")
        if st.button("🔎 Search"):
            results = search_index(ix, query)
            for i, hit in enumerate(results):
                with st.expander(f"**{hit.get('pe_number', 'Unknown')}** — {hit.get('program_title', '')}"):
                    st.markdown(highlight_text(hit.get("content", ""), query.split(), max_chars=800), unsafe_allow_html=True)

# ========== TAB 3: MY CAPABILITIES ==========
with tab3:
    st.header("⭐ My Capabilities")
    capabilities = load_capabilities()
    caps_text = st.text_area("Keywords (one per line)", "\n".join(capabilities), height=180)
    if st.button("💾 Save Keywords"):
        save_capabilities([x.strip() for x in caps_text.split("\n") if x.strip()])
        st.success("Keywords saved!")

# ========== TAB 4: POC RESEARCH HELPER ==========
with tab4:
    st.header("🧭 POC Research Helper")
    pe = st.text_input("Program Element (e.g. 0601234N)")
    title = st.text_input("Program Title")
    if st.button("Generate Search Links"):
        queries = build_poc_queries(pe, title, [])
        for label, q in queries.items():
            st.code(q)
            if st.button(f"Open {label}", key=label):
                open_search_in_browser(q)

# ========== TAB 5: HELP ==========
with tab5:
    st.header("Help & About")
    st.markdown("""
    **How to use:**
    1. Go to **Data Ingestion** tab and upload PDF(s) from comptroller.defense.gov
    2. Click **Scan & Build / Update Index**
    3. Use **Search** tab to find programs by keywords
    4. Use **My Capabilities** to score programs against what you offer
    5. Use **POC Research Helper** to generate outreach searches

    **Tip**: Start with smaller volumes (DARPA, MDA, or one Navy book) to test.
    """)

st.caption("v2.4 • Upload only • May 2026")