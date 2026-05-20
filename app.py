#!/usr/bin/env python3
"""
DoD Budget Justification Keyword Scout (BudgetPOC Scout)
Clean 5-Tab UI + Grok AI Powered
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
from openai import OpenAI

APP_NAME = "DoD Budget Justification Keyword Scout"
INDEX_PATH = "./whoosh_index"
CAPABILITIES_FILE = "my_capabilities.json"

# ==================== GROK SETUP ====================
GROK_API_KEY = st.secrets.get("GROK_API_KEY", "")

def get_grok():
    if not GROK_API_KEY:
        return None
    return OpenAI(api_key=GROK_API_KEY, base_url="https://api.x.ai/v1")

def grok_parse(text):
    client = get_grok()
    if not client: return None
    try:
        response = client.chat.completions.create(
            model="grok-2-1212",
            messages=[{"role": "user", "content": f"Extract PE number, program title, justification summary, key capabilities, and funding from this DoD budget text. Return clean JSON.\n\n{text[:6000]}"}],
            temperature=0.1, max_tokens=1200
        )
        return response.choices[0].message.content
    except: return None

def grok_poc_research(pe, title):
    client = get_grok()
    if not client: return None
    try:
        response = client.chat.completions.create(
            model="grok-2-1212",
            messages=[{"role": "user", "content": f"Act as a defense BD expert. For PE {pe} - {title}, give me: 1) Best LinkedIn search queries, 2) Best way to find TPOC email, 3) Suggested email subject lines. Be specific."}],
            temperature=0.3, max_tokens=1000
        )
        return response.choices[0].message.content
    except: return None

# ==================== CORE FUNCTIONS ====================
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
    except: return docs
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
            if parts: docs.append({"id": f"{src}_{pages[0]}_{pages[-1]}", "pe_number": pe, "program_title": title, "source": src, "pages": f"{pages[0]}-{pages[-1]}", "content": "\n\n".join(parts)})
            pe = new_pe
            title = txt.split('\n')[0][:60]
            parts = [txt]
            pages = [i+1]
        else:
            parts.append(txt)
            pages.append(i+1)
    if parts: docs.append({"id": f"{src}_{pages[0]}_{pages[-1]}", "pe_number": pe, "program_title": title, "source": src, "pages": f"{pages[0]}-{pages[-1]}", "content": "\n\n".join(parts)})
    doc.close()
    return docs

def get_or_create_index():
    schema = Schema(id=ID(unique=True, stored=True), pe_number=KEYWORD(stored=True), program_title=TEXT(stored=True), source=TEXT(stored=True), pages=STORED(), content=TEXT(stored=True, analyzer=StemmingAnalyzer()))
    if not os.path.exists(INDEX_PATH):
        os.makedirs(INDEX_PATH)
        return whoosh_index.create_in(INDEX_PATH, schema)
    try: return whoosh_index.open_dir(INDEX_PATH)
    except:
        shutil.rmtree(INDEX_PATH)
        os.makedirs(INDEX_PATH)
        return whoosh_index.create_in(INDEX_PATH, schema)

def add_to_index(ix, docs):
    w = ix.writer()
    for d in docs: w.update_document(**d)
    w.commit()
    return len(docs)

def search_index(query, limit=25):
    try:
        ix = whoosh_index.open_dir(INDEX_PATH)
        parser = MultifieldParser(["content", "program_title"], schema=ix.schema)
        with ix.searcher() as s:
            results = s.search(parser.parse(query), limit=limit)
            return [{"pe_number": r.get("pe_number", "Unknown"), "program_title": r.get("program_title", ""), "content": r.get("content", "")[:900]} for r in results]
    except: return []

def load_capabilities():
    if os.path.exists(CAPABILITIES_FILE):
        try: return json.load(open(CAPABILITIES_FILE))["keywords"]
        except: pass
    return ["avionics", "harness", "connector", "electro-mechanical", "MIL-STD", "RDT&E", "payload", "interconnect"]

def save_capabilities(keywords):
    json.dump({"keywords": keywords}, open(CAPABILITIES_FILE, "w"))

# ==================== UI ====================
st.set_page_config(page_title=APP_NAME, page_icon="🎯", layout="wide")
st.title("🎯 DoD Budget Justification Keyword Scout")
st.caption("Search official DoD budget justifications • Target keywords • Research POCs • Built for defense contractors & SDVOSBs")

with st.sidebar:
    st.header("Index Status")
    try:
        ix = whoosh_index.open_dir(INDEX_PATH)
        with ix.searcher() as s: count = s.doc_count()
        st.success(f"✅ {count:,} sections indexed")
    except:
        st.warning("No index yet")

    st.divider()
    st.header("Grok AI")
    api_key = st.text_input("xAI API Key", type="password", value=GROK_API_KEY)
    if api_key: GROK_API_KEY = api_key
    use_grok = st.checkbox("Use Grok for parsing & POC research", value=True)

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

    if st.button("🚀 Scan & Build / Update Index", type="primary", disabled=not pdfs):
        ix = get_or_create_index()
        total = 0
        for p in pdfs:
            st.write(f"Processing {os.path.basename(p)}...")
            docs = process_pdf(p)
            if docs:
                added = add_to_index(ix, docs)
                total += added
        st.success(f"✅ Indexed {total} sections!")
        if tmp: shutil.rmtree(tmp)
        st.rerun()

# ========== TAB 2: SEARCH & TARGET ==========
with tab2:
    st.header("🔍 Search Budget Justifications")
    query = st.text_input("Search query", value="harness OR connector OR payload")
    if st.button("🔎 Search", type="primary"):
        results = search_index(query)
        if not results:
            st.info("No matches found")
        for hit in results:
            with st.expander(f"**{hit['pe_number']}** — {hit['program_title']}"):
                st.write(hit['content'])

# ========== TAB 3: MY CAPABILITIES ==========
with tab3:
    st.header("⭐ My Capabilities")
    capabilities = load_capabilities()
    caps_text = st.text_area("Keywords (one per line)", "\n".join(capabilities), height=160)
    if st.button("💾 Save Keywords"):
        save_capabilities([x.strip() for x in caps_text.split("\n") if x.strip()])
        st.success("Saved!")

# ========== TAB 4: POC RESEARCH HELPER (GROK POWERED) ==========
with tab4:
    st.header("🧭 POC Research Helper")
    st.markdown("**Find real people to contact** (Program Managers, TPOCs, Contracting Officers)")

    col1, col2 = st.columns(2)
    with col1:
        pe = st.text_input("Program Element (e.g. 0601234N)")
    with col2:
        title = st.text_input("Program Title (optional)")

    if st.button("Research POCs with Grok", type="primary"):
        if not pe:
            st.warning("Enter a Program Element number")
        else:
            if use_grok and GROK_API_KEY:
                with st.spinner("Grok is researching..."):
                    result = grok_poc_research(pe, title)
                    if result:
                        st.subheader("Grok's POC Research")
                        st.markdown(result)
            else:
                st.info("Grok is disabled or no API key. Using basic version.")
                st.code(f'"{pe}" "{title}" ("Program Manager" OR TPOC) (Navy OR "Air Force" OR Army)')

# ========== TAB 5: HELP ==========
with tab5:
    st.header("ℹ️ Help & About")
    st.markdown("""
    **This tool now uses Grok AI** to help parse documents and find real Points of Contact.

st.caption("v4.1 • Grok Powered • May 2026")