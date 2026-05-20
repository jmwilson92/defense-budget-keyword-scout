#!/usr/bin/env python3
"""
DoD Budget Justification Keyword Scout (BudgetPOC Scout)
Clean version with Upload button only
"""

import os
import re
import json
import shutil
import tempfile
from pathlib import Path
import streamlit as st
import fitz
from whoosh import index as whoosh_index
from whoosh.fields import Schema, TEXT, ID, STORED, KEYWORD
from whoosh.analysis import StemmingAnalyzer
from whoosh.qparser import MultifieldParser

APP_NAME = "DoD Budget Justification Keyword Scout"
INDEX_PATH = "./whoosh_index"
CAPABILITIES_FILE = "my_capabilities.json"

DEFAULT_CAPABILITIES = ["avionics", "harness", "connector", "electro-mechanical", "MIL-STD", "RDT&E", "payload", "interconnect"]

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

def get_index():
    schema = Schema(id=ID(unique=True, stored=True), pe_number=KEYWORD(stored=True), program_title=TEXT(stored=True), source=TEXT(stored=True), pages=STORED(), content=TEXT(stored=True, analyzer=StemmingAnalyzer()))
    if not os.path.exists(INDEX_PATH):
        os.makedirs(INDEX_PATH)
        return whoosh_index.create_in(INDEX_PATH, schema)
    try:
        return whoosh_index.open_dir(INDEX_PATH)
    except:
        shutil.rmtree(INDEX_PATH)
        os.makedirs(INDEX_PATH)
        return whoosh_index.create_in(INDEX_PATH, schema)

def add_docs(ix, docs):
    w = ix.writer()
    for d in docs:
        w.update_document(**d)
    w.commit()
    return len(docs)

def do_search(ix, q, limit=20):
    p = MultifieldParser(["content", "program_title"], schema=ix.schema)
    with ix.searcher() as s:
        return s.search(p.parse(q), limit=limit)

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

with st.sidebar:
    st.header("Index")
    try:
        ix = whoosh_index.open_dir(INDEX_PATH)
        st.success(f"✅ {ix.searcher().doc_count():,} sections")
    except:
        st.warning("No index yet")

tab1, tab2, tab3, tab4 = st.tabs(["📥 Upload & Index", "🔍 Search", "⭐ My Keywords", "🧭 POC Helper"])

with tab1:
    st.header("Upload PDFs")
    files = st.file_uploader("Upload PDF(s)", type="pdf", accept_multiple_files=True)
    pdfs = []
    tmp = None
    if files:
        tmp = tempfile.mkdtemp()
        for f in files:
            p = os.path.join(tmp, f.name)
            with open(p, "wb") as out: out.write(f.getbuffer())
            pdfs.append(p)
        st.success(f"✅ {len(files)} ready")

    force = st.checkbox("Force rebuild")
    if st.button("🚀 Index Now", disabled=not pdfs):
        if force and os.path.exists(INDEX_PATH):
            shutil.rmtree(INDEX_PATH)
        ix = get_index()
        total = 0
        for p in pdfs:
            st.write(f"Processing {os.path.basename(p)}...")
            total += add_docs(ix, process_pdf(p))
        st.success(f"✅ Indexed {total} sections!")
        if tmp: shutil.rmtree(tmp)
        st.rerun()

with tab2:
    st.header("Search")
    q = st.text_input("Keywords", "harness OR connector OR payload")
    if st.button("Search"):
        try:
            ix = whoosh_index.open_dir(INDEX_PATH)
            for hit in do_search(ix, q):
                with st.expander(f"{hit.get('pe_number')} — {hit.get('program_title', '')}"):
                    st.write(hit.get("content", "")[:800])
        except:
            st.warning("No index yet")

with tab3:
    st.header("My Keywords")
    caps = load_capabilities()
    new = st.text_area("One per line", "\n".join(caps))
    if st.button("Save"):
        save_capabilities([x.strip() for x in new.splitlines() if x.strip()])
        st.success("Saved!")

with tab4:
    st.header("POC Research Helper")
    pe = st.text_input("Program Element")
    title = st.text_input("Program Title")
    if st.button("Generate Links"):
        st.code(f'"{pe}" "{title}" ("Program Manager" OR TPOC)')

st.caption("v2.5 • Upload only • May 2026")