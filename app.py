#!/usr/bin/env python3
"""
DoD Budget Justification Keyword Scout (BudgetPOC Scout)
Clean Professional UI + Useful POC Helper + Working Capabilities
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

def score_against_capabilities(docs, keywords):
    scored = []
    for doc in docs:
        content_lower = doc.get("content", "").lower()
        matches = [kw for kw in keywords if kw.lower() in content_lower]
        if matches:
            scored.append({
                **doc,
                "match_count": len(matches),
                "matched_keywords": ", ".join(matches[:6])
            })
    return sorted(scored, key=lambda x: x["match_count"], reverse=True)

# ==================== UI ====================
st.set_page_config(page_title=APP_NAME, page_icon="🎯", layout="wide")
st.title("🎯 DoD Budget Justification Keyword Scout")
st.caption("Search official DoD budget justifications • Target keywords • Research POCs • Built for defense contractors & SDVOSBs")

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
    st.header("📥 Upload & Index Budget PDFs")
    st.markdown("Upload one or more PDF justification books from comptroller.defense.gov")

    uploaded = st.file_uploader("Upload PDF(s)", type="pdf", accept_multiple_files=True)
    
    pdfs = []
    tmp = None
    if uploaded:
        tmp = tempfile.mkdtemp()
        for f in uploaded:
            p = os.path.join(tmp, f.name)
            with open(p, "wb") as out: out.write(f.getbuffer())
            pdfs.append(p)
        st.success(f"✅ {len(uploaded)} file(s) ready")

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
            with st.spinner(f"Processing {os.path.basename(p)}..."):
                docs = process_pdf(p)
                if docs:
                    added = add_to_index(ix, docs)
                    total += added
        
        st.success(f"✅ Indexed {total} sections from {len(pdfs)} files!")
        if tmp: shutil.rmtree(tmp)
        st.rerun()

    with st.expander("What gets indexed?"):
        st.markdown("""
        - The tool segments text into **Program Element (PE)** sections
        - Only substantial descriptive text is kept
        - Works with both RDT&E and Procurement justification books
        """)

# ========== TAB 2: SEARCH & TARGET ==========
with tab2:
    st.header("🔍 Search Budget Justifications")
    st.caption("Enter keywords or Whoosh query syntax")

    query = st.text_input("Search query", value="harness OR connector OR payload")

    col1, col2 = st.columns(2)
    with col1:
        limit = st.slider("Max results", 5, 50, 20, help="How many results to return")
    with col2:
        min_score = st.slider("Min score", 0.0, 20.0, 0.0, step=0.5, help="Only show strong matches (0 = show all)")

    if st.button("🔎 Search", type="primary"):
        results = search_index(query, limit)
        if not results:
            st.info("No matches found. Try different keywords.")
        else:
            st.success(f"Found {len(results)} results")
            for hit in results:
                with st.expander(f"**{hit['pe_number']}** — {hit['program_title']}"):
                    st.write(hit['content'])

# ========== TAB 3: MY CAPABILITIES (FINISHED) ==========
with tab3:
    st.header("⭐ My Capabilities")
    st.markdown("Edit keywords that describe what you sell or do. The tool will score every indexed section against your keywords.")

    capabilities = load_capabilities()
    caps_text = st.text_area("Keywords (one per line)", "\n".join(capabilities), height=160)
    
    col1, col2 = st.columns([1, 3])
    with col1:
        if st.button("💾 Save Keywords"):
            save_capabilities([x.strip() for x in caps_text.split("\n") if x.strip()])
            st.success("Keywords saved!")
    with col2:
        if st.button("↩️ Reset to Defaults"):
            save_capabilities(DEFAULT_CAPABILITIES)
            st.rerun()

    st.divider()

    if st.button("🚀 Score All Documents Against My Keywords", type="primary"):
        try:
            ix = whoosh_index.open_dir(INDEX_PATH)
            all_docs = []
            with ix.searcher() as s:
                for doc in s.all_stored_fields():
                    all_docs.append({
                        "pe_number": doc.get("pe_number", "Unknown"),
                        "program_title": doc.get("program_title", ""),
                        "source": doc.get("source", ""),
                        "content": doc.get("content", "")
                    })
            
            scored = score_against_capabilities(all_docs, capabilities)
            
            if not scored:
                st.warning("No matches found. Try adding more specific keywords.")
            else:
                st.success(f"Found {len(scored)} sections that match your capabilities!")
                for item in scored[:15]:
                    with st.expander(f"**{item['pe_number']}** — {item['program_title']} ({item['match_count']} matches)"):
                        st.write(f"**Matched keywords:** {item['matched_keywords']}")
                        st.write(item['content'][:600])
        except:
            st.warning("No index found. Please upload and index PDFs first.")

# ========== TAB 4: POC RESEARCH HELPER (IMPROVED) ==========
with tab4:
    st.header("🧭 POC Research Helper")
    st.markdown("Generate targeted, actionable research queries and outreach materials.")

    col_pe, col_title = st.columns(2)
    with col_pe:
        pe = st.text_input("Program Element (e.g. 0601234N)")
    with col_title:
        title = st.text_input("Program Title")

    if st.button("Generate Research Package", type="primary"):
        if not pe and not title:
            st.warning("Enter at least a PE number or program title")
        else:
            base = f'"{pe}" "{title}"' if title else f'"{pe}"'
            
            st.subheader("1. Google / LinkedIn Searches")
            st.code(f'{base} ("Program Manager" OR TPOC OR "Technical Point of Contact" OR "Contracting Officer") (Navy OR "Air Force" OR Army OR DARPA OR MDA)')
            st.code(f'{base} ("Program Manager" OR TPOC) site:linkedin.com')
            
            st.subheader("2. SBIR / STTR Opportunities")
            st.code(f'{pe} OR "{title}" site:sbir.gov OR site:sttr.gov')
            
            st.subheader("3. Recent Awards & Spending")
            st.code(f'{base} (award OR contract OR "program element") site:usaspending.gov')
            
            st.subheader("4. SAM.gov Opportunities")
            st.code(f'{pe} OR "{title}" defense harness OR connector OR avionics')
            
            st.subheader("5. Suggested Outreach Email Subject Lines")
            st.code(f"Re: FY27 {title or 'Program'} - {pe} Capability Alignment")
            st.code(f"Support for {title or 'Program'} ({pe}) - Advanced Interconnect Solutions")

# ========== TAB 5: HELP & ABOUT ==========
with tab5:
    st.header("ℹ️ Help & About")
    
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
    - Capability scoring against your keywords
    - POC research helper with actionable queries

    Good luck landing those conversations and contracts.
    """)

    st.caption("v3.8 • Clean UI + Useful POC Helper + Working Capabilities • May 2026")

st.divider()
st.caption("Run locally with `streamlit run app.py` after `pip install -r requirements.txt`")