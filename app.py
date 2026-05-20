#!/usr/bin/env python3
"""
DoD Budget Justification Keyword Scout (BudgetPOC Scout)
Full UI - All 5 tabs + Reliable Indexing
"""

import os
import re
import json
import shutil
import tempfile
import streamlit as st
import fitz
from whoosh import index as whoosh_index
from whoosh.fields import Schema, TEXT, ID, STORED, KEYWORD
from whoosh.analysis import StemmingAnalyzer
from whoosh.qparser import MultifieldParser

APP_NAME = "DoD Budget Justification Keyword Scout"
INDEX_PATH = "./whoosh_index"
CAPABILITIES_FILE = "my_capabilities.json"

DEFAULT_CAPABILITIES = [
    "avionics", "harness", "connector", "electro-mechanical", "electromechanical",
    "MIL-STD", "RDT&E", "payload", "interconnect", "cable assembly", "backshell",
    "wiring", "cabling", "integration", "test equipment", "flight hardware",
    "ground support", "defense manufacturing", "aerospace component"
]

def clean_text(t):
    t = re.sub(r'[ \t]+', ' ', t)
    t = re.sub(r'\n{3,}', '\n\n', t)
    for x in [r'\bUNCLASSIFIED\b', r'THIS PAGE INTENTIONALLY LEFT BLANK']:
        t = re.sub(x, '', t, flags=re.IGNORECASE)
    return t.strip()

def extract_pe(text):
    m = re.search(r'PE\s+(\d{7}[A-Z]?)', text, re.IGNORECASE)
    return m.group(1).upper() if m else None

def process_pdf(path):
    docs = []
    try:
        doc = fitz.open(path)
    except:
        return docs
    src = os.path.basename(path)
    pe = "General"
    title = src.replace(".pdf", "")
    parts = []
    pages = []
    for i, page in enumerate(doc):
        txt = clean_text(page.get_text("text"))
        if len(txt) < 50: continue
        new_pe = extract_pe(txt)
        if new_pe and new_pe != pe:
            if parts:
                docs.append({"id": f"{src}_{pages[0]}_{pages[-1]}", "pe_number": pe, "program_title": title, "source": src, "pages": f"{pages[0]}-{pages[-1]}", "content": "\n\n".join(parts)})
            pe = new_pe
            title = txt.split('\n')[0][:60]
            parts = [txt]
            pages = [i+1]
        else:
            parts.append(txt)
            pages.append(i+1)
    if parts:
        docs.append({"id": f"{src}_{pages[0]}_{pages[-1]}", "pe_number": pe, "program_title": title, "source": src, "pages": f"{pages[0]}-{pages[-1]}", "content": "\n\n".join(parts)})
    doc.close()
    return docs

def get_or_create_index():
    schema = Schema(
        id=ID(unique=True, stored=True),
        pe_number=KEYWORD(stored=True),
        program_title=TEXT(stored=True),
        source=TEXT(stored=True),
        pages=STORED(),
        content=TEXT(stored=True, analyzer=StemmingAnalyzer())
    )
    if not os.path.exists(INDEX_PATH):
        os.makedirs(INDEX_PATH)
        return whoosh_index.create_in(INDEX_PATH, schema)
    try:
        return whoosh_index.open_dir(INDEX_PATH)
    except:
        shutil.rmtree(INDEX_PATH)
        os.makedirs(INDEX_PATH)
        return whoosh_index.create_in(INDEX_PATH, schema)

def add_to_index(ix, docs):
    w = ix.writer()
    for d in docs:
        w.update_document(**d)
    w.commit()
    return len(docs)

def search_index(query, limit=25):
    try:
        ix = whoosh_index.open_dir(INDEX_PATH)
        parser = MultifieldParser(["content", "program_title"], schema=ix.schema)
        with ix.searcher() as s:
            results = s.search(parser.parse(query), limit=limit)
            return [{"pe_number": r.get("pe_number", "Unknown"), 
                    "program_title": r.get("program_title", ""), 
                    "content": r.get("content", "")[:900]} for r in results]
    except:
        return []

def load_capabilities():
    if os.path.exists(CAPABILITIES_FILE):
        try:
            return json.load(open(CAPABILITIES_FILE))["keywords"]
        except:
            pass
    return DEFAULT_CAPABILITIES

def save_capabilities(keywords):
    json.dump({"keywords": keywords}, open(CAPABILITIES_FILE, "w"))

# UI
st.set_page_config(page_title=APP_NAME, page_icon="🎯", layout="wide")
st.title("🎯 DoD Budget Justification Keyword Scout")
st.caption("Search official DoD budget justifications & descriptive summaries • Target keywords in line items • Research POCs & initiate conversations • Built for defense contractors & SDVOSBs")

with st.sidebar:
    st.header("Index Status")
    try:
        ix = whoosh_index.open_dir(INDEX_PATH)
        with ix.searcher() as s:
            count = s.doc_count()
        st.success(f"✅ {count:,} sections indexed")
    except:
        st.warning("No index yet")

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📥 Data Ingestion", 
    "🔍 Search & Target", 
    "⭐ My Capabilities", 
    "🧭 POC Research Helper", 
    "ℹ️ Help & About"
])

# ========== TAB 1: DATA INGESTION ==========
with tab1:
    st.header("Ingest & Index Budget Justification PDFs")
    st.markdown("**Upload one or more PDF files** (justification books from comptroller.defense.gov)")

    uploaded = st.file_uploader("Upload PDF(s)", type="pdf", accept_multiple_files=True)
    
    pdfs = []
    tmp = None
    if uploaded:
        tmp = tempfile.mkdtemp()
        for f in uploaded:
            p = os.path.join(tmp, f.name)
            with open(p, "wb") as out: out.write(f.getbuffer())
            pdfs.append(p)
        st.success(f"✅ {len(uploaded)} file(s) ready to process")

    col1, col2 = st.columns(2)
    with col1:
        force = st.checkbox("Force full rebuild")
    with col2:
        max_n = st.number_input("Max PDFs (0 = all)", 0, 20, 0)

    if st.button("🚀 Scan & Build / Update Index", type="primary", disabled=not pdfs):
        if force and os.path.exists(INDEX_PATH):
            shutil.rmtree(INDEX_PATH)
        
        ix = get_or_create_index()
        total = 0
        
        for p in pdfs:
            st.write(f"Processing {os.path.basename(p)}...")
            docs = process_pdf(p)
            if docs:
                added = add_to_index(ix, docs)
                total += added
        
        st.success(f"✅ Indexed {total} sections from {len(pdfs)} files!")
        if tmp: shutil.rmtree(tmp)
        st.rerun()

    st.divider()
    st.subheader("What gets indexed?")
    st.markdown("""
    - The tool segments text into **Program Element (PE)** sections
    - Only substantial descriptive text is kept
    - Works with both RDT&E and Procurement justification books
    """)

# ========== TAB 2: SEARCH & TARGET ==========
with tab2:
    st.header("Keyword Search Across Budget Justifications")
    st.caption("Enter keywords or Whoosh query syntax")

    query = st.text_input("Search query", value="harness OR connector OR payload")
    
    col1, col2 = st.columns(2)
    with col1:
        limit = st.slider("Max results", 5, 50, 20)
    with col2:
        min_score = st.slider("Min score", 0.0, 20.0, 0.0, step=0.5)

    if st.button("🔎 Search", type="primary"):
        results = search_index(query, limit)
        if not results:
            st.info("No matches found. Try different keywords.")
        else:
            st.success(f"Found {len(results)} results")
            for hit in results:
                with st.expander(f"**{hit['pe_number']}** — {hit['program_title']}"):
                    st.write(hit['content'])

# ========== TAB 3: MY CAPABILITIES ==========
with tab3:
    st.header("⭐ My Capabilities")
    st.markdown("Edit keywords that describe what you sell or do. The tool will help you find matching programs.")

    capabilities = load_capabilities()
    caps_text = st.text_area("Keywords (one per line)", "\n".join(capabilities), height=180)
    
    col1, col2 = st.columns([1, 3])
    with col1:
        if st.button("💾 Save Keywords"):
            save_capabilities([x.strip() for x in caps_text.split("\n") if x.strip()])
            st.success("Keywords saved!")
    with col2:
        if st.button("↩️ Reset to Defaults"):
            save_capabilities(DEFAULT_CAPABILITIES)
            st.rerun()

    st.info("Capability scoring coming in next update. Use Search tab for now.")

# ========== TAB 4: POC RESEARCH HELPER ==========
with tab4:
    st.header("🧭 POC Research Helper")
    st.markdown("Generate targeted search queries to find Program Managers, TPOCs, and opportunities.")

    pe = st.text_input("Program Element (e.g. 0601234N)")
    title = st.text_input("Program Title")
    
    if st.button("Generate Search Links", type="primary"):
        if not pe and not title:
            st.warning("Enter at least a PE number or program title")
        else:
            base = f'"{pe}" "{title}"' if title else f'"{pe}"'
            st.subheader("Ready-to-Use Searches")
            st.code(f'{base} ("Program Manager" OR TPOC OR "Technical Point of Contact") (Navy OR "Air Force" OR Army OR DARPA)')
            st.code(f'{base} site:sbir.gov OR site:sttr.gov')
            st.code(f'{base} (award OR contract) site:usaspending.gov')

# ========== TAB 5: HELP & ABOUT ==========
with tab5:
    st.header("Help & About")
    
    with st.expander("Where to Download Budget PDFs", expanded=True):
        st.markdown("""
        **Primary Source**: [Under Secretary of Defense (Comptroller) Budget Materials](https://comptroller.defense.gov/Budget-Materials/)
        
        - Go to current FY → **Budget Justification** section
        - Download RDT&E and Procurement volumes
        - Start with smaller ones (DARPA, MDA, or one Navy volume) to test
        """)

    st.divider()
    st.subheader("About This Tool")
    st.markdown("""
    **DoD Budget Justification Keyword Scout** helps defense contractors quickly find funded programs that match their capabilities by mining official DoD budget justification books.

    **Features:**
    - Direct PDF upload (no local folder needed)
    - Keyword search across Program Elements
    - POC research helper with pre-built queries
    - All processing happens on your machine or Streamlit Cloud

    Good luck landing those conversations and contracts.
    """)

    st.caption("v3.5 • Full UI • May 2026")

st.divider()
st.caption("Run locally with `streamlit run app.py` after `pip install -r requirements.txt`")