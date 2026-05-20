#!/usr/bin/env python3
"""
DoD Budget Justification Keyword Scout (BudgetPOC Scout)
Full UI - All 5 tabs preserved + Upload button only in Data Ingestion
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

def get_all_indexed_documents(ix):
    docs = []
    with ix.searcher() as searcher:
        for doc in searcher.all_stored_fields():
            docs.append({
                "id": doc.get("id"),
                "pe_number": doc.get("pe_number", "Unknown"),
                "program_title": doc.get("program_title", ""),
                "source": doc.get("source", ""),
                "pages": doc.get("pages", ""),
                "content": doc.get("content", "")[:2000],
            })
    return docs

def score_document(content, keywords):
    content_lower = content.lower()
    matched = [kw for kw in keywords if kw.lower() in content_lower]
    return len(matched), matched

# ----------------------------- STREAMLIT UI -----------------------------
st.set_page_config(page_title=APP_NAME, page_icon="🎯", layout="wide")
st.title("🎯 DoD Budget Justification Keyword Scout")
st.caption("Search official DoD budget justifications & descriptive summaries • Target keywords in line items • Research POCs & initiate conversations • Built for defense contractors & SDVOSBs")

with st.sidebar:
    st.header("Index Status")
    index_path = st.text_input("Whoosh Index Location", value=DEFAULT_INDEX_PATH)
    
    ix = None
    index_exists = os.path.exists(os.path.join(index_path, "MAIN_write.lock")) or os.path.exists(os.path.join(index_path, "_MAIN_1.toc"))
    
    if index_exists:
        try:
            ix = whoosh_index.open_dir(index_path)
            with ix.searcher() as searcher:
                doc_count = searcher.doc_count()
            st.success(f"✅ Index ready — {doc_count:,} sections indexed")
        except Exception as e:
            st.error(f"Index error: {e}. Try rebuilding.")
            index_exists = False
    else:
        st.warning("No index found. Upload PDFs below.")

# Main tabs
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📥 Data Ingestion", 
    "🔍 Search & Target", 
    "⭐ My Capabilities & Best Matches", 
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
                st.warning("Old index deleted.")

            ix = create_or_open_index(index_path)

            progress_bar = st.progress(0.0)
            status_text = st.empty()
            total_docs_added = 0
            start_time = time.time()

            for idx, pdf_path in enumerate(pdf_files_to_process):
                filename = os.path.basename(pdf_path)
                status_text.text(f"Processing ({idx+1}/{len(pdf_files_to_process)}): {filename}")
                docs = process_pdf_to_documents(str(pdf_path))
                added = add_documents_to_index(ix, docs)
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
    - The tool tries to segment text into **Program Element (PE)** sections using common patterns in R-2 / R-3 exhibits.
    - Pages without a clear PE go into "General Overview / Front Matter".
    - Only substantial text chunks (> ~300 chars) are kept.
    - Both RDT&E (rich descriptions) and Procurement justification books work.
    """)

# ========== TAB 2: SEARCH & TARGET ==========
with tab2:
    st.header("Keyword Search Across Budget Justifications")
    st.caption("Enter keywords or Whoosh query syntax. Results are ranked by relevance to your search.")

    if not index_exists or ix is None:
        st.warning("Please build or load an index first in the Data Ingestion tab.")
    else:
        query = st.text_input(
            "Search query (keywords, phrases in \"quotes\", +must +have for AND)",
            value="harness OR connector OR \"electro-mechanical\" OR payload",
            placeholder="e.g. harness connector OR \"electro-mechanical\" +avionics",
            help="Whoosh syntax supported: +keyword (must), -keyword (not), \"exact phrase\", keyword~ (fuzzy)"
        )

        col1, col2, col3 = st.columns(3)
        with col1:
            limit = st.slider("Max results", 5, 100, 25, step=5)
        with col2:
            min_score = st.slider("Min score (optional)", 0.0, 20.0, 0.0, step=0.5)
        with col3:
            filter_source = st.text_input("Filter by source contains (optional)", placeholder="Navy or DARPA")

        if st.button("🔎 Search", type="primary"):
            with st.spinner("Searching index..."):
                results = search_index(ix, query, limit=limit)

            if not results:
                st.info("No matches found. Try broader keywords or check your index.")
            else:
                st.success(f"Found {len(results)} results (showing top {min(len(results), limit)})")
                
                for i, hit in enumerate(results):
                    score = hit.score
                    if min_score > 0 and score < min_score:
                        continue

                    pe = hit.get("pe_number", "Unknown")
                    title = hit.get("program_title", "")
                    source = hit.get("source", "")
                    pages = hit.get("pages", "")
                    content = hit.get("content", "")

                    query_keywords = re.findall(r'[\w\-]+', query.lower())

                    with st.expander(f"**{pe}** — {title or 'Program Description'}  |  {source} (pp. {pages})  |  score: {score:.2f}", expanded=(i < 3)):
                        st.markdown(f"**Source:** {source} &nbsp;&nbsp;|&nbsp;&nbsp; **Pages:** {pages}")
                        if title:
                            st.markdown(f"**Program Title:** {title}")

                        snippet = highlight_text(content, query_keywords, max_chars=800)
                        st.markdown(snippet, unsafe_allow_html=True)

                        if st.checkbox(f"Show full extracted text for this section", key=f"full_{i}"):
                            st.text_area("Full text", content, height=300, key=f"ta_{i}")

                        if st.button(f"🧭 Research POC & Opportunities for this item", key=f"poc_{i}"):
                            st.session_state["selected_hit"] = {
                                "pe_number": pe,
                                "program_title": title,
                                "source": source,
                                "pages": pages,
                                "content": content[:1500],
                                "matched_keywords": query_keywords,
                            }
                            st.info("Scroll down or switch to the **POC Research Helper** tab. Your selection is loaded there.")

# ========== TAB 3: MY CAPABILITIES & BEST MATCHES ==========
with tab3:
    st.header("⭐ Score Everything Against *Your* Capabilities")
    st.markdown("Edit the list below with the exact keywords/phrases that describe what you sell or do. The tool will score every indexed section and show you the **best matching funded programs**.")

    capabilities = load_capabilities()

    with st.expander("Edit / Customize My Keywords (saved automatically)", expanded=True):
        caps_text = st.text_area(
            "One keyword or phrase per line",
            value="\n".join(capabilities),
            height=200,
            help="Add very specific terms: your processes, part numbers you support, platforms, certifications, etc."
        )
        new_caps = [line.strip() for line in caps_text.split("\n") if line.strip()]
        
        col_save1, col_save2 = st.columns([1, 3])
        with col_save1:
            if st.button("💾 Save Keywords"):
                save_capabilities(new_caps)
                st.success("Keywords saved!")
                capabilities = new_caps
                st.rerun()
        with col_save2:
            if st.button("↩️ Reset to Defaults"):
                save_capabilities(DEFAULT_CAPABILITIES)
                st.rerun()

    st.divider()

    if not index_exists or ix is None:
        st.info("Build an index first to score documents.")
    else:
        if st.button("🚀 Find Best Matches for My Capabilities", type="primary"):
            with st.spinner("Scoring all indexed sections against your keywords... (can take 10-60s depending on index size)"):
                all_docs = get_all_indexed_documents(ix)
                scored = []
                for d in all_docs:
                    count, matched = score_document(d.get("content", ""), capabilities)
                    if count > 0:
                        scored.append({
                            **d,
                            "match_count": count,
                            "matched_keywords": ", ".join(matched[:8]),
                        })
                scored.sort(key=lambda x: x["match_count"], reverse=True)

            if not scored:
                st.warning("No matches found. Try adding more or different keywords.")
            else:
                st.success(f"Top matches: {len(scored)} sections contain at least one of your keywords. Showing highest overlap first.")
                df = pd.DataFrame(scored[:30])
                st.dataframe(df[["pe_number", "program_title", "source", "match_count", "matched_keywords"]], use_container_width=True)

# ========== TAB 4: POC RESEARCH HELPER ==========
with tab4:
    st.header("🧭 POC & Opportunity Research Helper")
    st.markdown("""
    Budget justifications rarely contain direct emails. This panel helps you **generate precise, high-signal search queries**.
    """)

    default_pe = ""
    default_title = ""

    if "selected_hit" in st.session_state:
        hit = st.session_state["selected_hit"]
        default_pe = hit.get("pe_number", "")
        default_title = hit.get("program_title", "")
        st.info(f"Loaded from previous search: **{default_pe}** — {default_title}")

    col_pe, col_title = st.columns(2)
    with col_pe:
        pe_number = st.text_input("Program Element (PE) Number", value=default_pe, placeholder="0601234N or 0603176C")
    with col_title:
        program_title = st.text_input("Program Title / Name", value=default_title, placeholder="Advanced Avionics Interconnect or similar")

    if st.button("Generate Research Queries & Links", type="primary"):
        if not pe_number and not program_title:
            st.warning("Enter at least a PE number or program title.")
        else:
            queries = build_poc_queries(pe_number, program_title, [])
            for label, q in queries.items():
                with st.expander(label, expanded=True):
                    st.code(q)
                    if st.button(f"🔗 Open this search in browser", key=f"open_{label}"):
                        open_search_in_browser(q)

# ========== TAB 5: HELP & ABOUT ==========
with tab5:
    st.header("Help, Sources & Best Practices")
    
    with st.expander("Where to Download the Official Budget Justification PDFs", expanded=True):
        st.markdown("""
        **Primary Source**: [Under Secretary of Defense (Comptroller) Budget Materials](https://comptroller.defense.gov/Budget-Materials/)
        
        - Go to the current FY → **Budget Justification** section
        - Download RDT&E and Procurement volumes
        - Start with smaller ones (DARPA, MDA, or one Navy volume) to test
        """)

    st.divider()
    st.subheader("About This Tool")
    st.markdown("""
    **DoD Budget Justification Keyword Scout** was built to give defense contractors a practical way to mine public budget justification books.

    **Features:**
    - Upload PDFs directly (no local folder needed)
    - Keyword search across Program Elements
    - Capability scoring against your keywords
    - POC research helper with pre-built search queries

    Good luck landing those conversations and contracts.
    """)

    st.caption("v2.10 • Full UI Preserved • May 2026")

# Footer
st.divider()
st.caption("Run locally with `streamlit run app.py` after `pip install -r requirements.txt`. All data stays on your machine.")