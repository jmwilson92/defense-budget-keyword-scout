# DoD Budget Justification Keyword Scout (BudgetPOC Scout)

**For Defense Contractors and Manufacturers**  
Search thousands of pages of official DoD budget justifications and descriptive summaries. Target line items and program elements (PEs) that match *your* capabilities. Identify funded programs, then use built-in tools to research and contact the right POCs, program managers, or contracting officers.

This tool helps you:
- Quickly comb through RDT&E and Procurement justification books.
- Find programs that need exactly what you make or do.
- Generate targeted outreach queries for LinkedIn, Google, agency sites, SBIR/STTR, SAM.gov, and USAspending.gov.
- Build a prioritized list of opportunities based on *your* specific keywords and capabilities.

**A general-purpose tool for any defense contractor or manufacturer in the aerospace, defense, and space supply chain.**

## Quick Start

### For Deployed Version (Easiest - Recommended)
1. Open the live app.
2. Go to the **Data Ingestion** tab.
3. Choose one of the three options:
   - **📤 Upload PDF files** — Drag & drop PDFs directly (works great on Streamlit Cloud)
   - **🔗 Paste PDF URLs** — Paste direct links to official justification PDFs (one per line)
   - **📁 Local folder path** — Only for running locally on your computer

4. Click **🚀 Scan & Build / Update Index**

### For Local Run
```bash
git clone https://github.com/jmwilson92/defense-budget-keyword-scout.git
cd defense-budget-keyword-scout
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## New Feature: Flexible PDF Input
The app now supports three ways to add PDFs:
- Direct file upload (best for cloud)
- Paste direct PDF URLs (auto-download)
- Local folder path

This makes it much easier to use on Streamlit Cloud without needing local files.