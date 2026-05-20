# DoD Budget Justification Keyword Scout (BudgetPOC Scout)

**For Defense Contractors, SDVOSBs, and Manufacturers**  
Search thousands of pages of official DoD budget justifications and descriptive summaries. Target line items and program elements (PEs) that match your capabilities (e.g., harnesses, connectors, electro-mechanical assemblies, MIL-SPEC work). Identify funded programs, then use built-in tools to research and contact the right POCs, program managers, or contracting officers.

This tool helps you:
- Quickly comb through RDT&E and Procurement justification books.
- Find programs that need exactly what you make or do.
- Generate targeted outreach queries for LinkedIn, Google, agency sites, SBIR/STTR, SAM.gov, and USAspending.gov.
- Build a prioritized list of opportunities based on *your* specific keywords and capabilities.

**Created for contractors like Wilson Precision Manufacturing and similar precision mfg / avionics / harness / connector specialists in the defense, aerospace, and space supply chain.**

## Why This Matters
Official budget justification books (R-2, R-3 exhibits, Mission Descriptions, Accomplishments/Planned Programs) contain rich narrative descriptions of what each program is building, testing, or fielding. These are gold for matching your technical capabilities to funded work — often before RFPs hit SAM.gov. Many line items describe needs for custom cabling, connectors (D38999, Glenair, etc.), backshells, overmolding, potting, IPC-A-620 assemblies, MIL-STD testing, etc.

**Important on POCs**: Budget books almost never list individual emails or names per PE (for good reason). This tool gives you the *what* and *where*, then arms you with precise search queries and links to find the humans (Program Managers / TPOCs / KOs). Real outreach often involves:
- LinkedIn searches + InMail or connection requests.
- Checking program office "Industry Day" or "Outreach" pages.
- SBIR/STTR topic authors (many list POC).
- Recent award winners on USAspending (then supplier diversity or small business liaison).
- Primes on the program (they sub out harness/connector work constantly).

## Quick Start (Local Desktop App)

1. **Install Python 3.10+** (recommended via pyenv or official).

2. **Clone or download this folder** to your machine.

3. **Create venv and install**:
   ```bash
   cd budget_scout
   python -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

4. **Download the latest DoD Budget Justification PDFs** (free, public):
   - Go to: https://comptroller.defense.gov/Budget-Materials/ (or search "DoD Comptroller Budget Materials FY202X")
   - Navigate to the current FY (e.g., FY2026 or FY2027) → **Budget Justification** or **Detailed Budget Documents**.
   - Download relevant volumes:
     - **Defense-Wide RDT&E**: DARPA, MDA, SOCOM, OSD volumes (great for advanced tech, space, missiles, special ops).
     - **Service-specific**:
       - Navy / USMC: Navy comptroller site or linked RDT&E and Procurement books (heavy in San Diego area work — E-2, helos, shipboard, avionics).
       - Air Force / Space Force.
       - Army.
     - Also grab **Procurement (P-1)** justification books for production line items.
   - Put them in one folder, e.g. `~/DoD_Budgets/FY2026_Justifications/` (you can have subfolders; the tool scans recursively for *.pdf).

   **Tip**: Start with 2-3 smaller or high-interest volumes (e.g., one DARPA + one Navy RDT&E) to test. Full set for one FY can be several GB and take 10-30+ min to index first time.

5. **Run the app**:
   ```bash
   streamlit run app.py
   ```
   It opens in your browser (localhost:8501).

6. **First use**:
   - Go to **Data Ingestion** tab.
   - Enter the full path to your PDFs folder.
   - Click **Scan & Build Index**.
   - Watch progress. It extracts text, detects Program Elements where possible, and builds a fast Whoosh search index (persisted on disk so you don't re-process every time).
   - Once done, switch to **Search & Target** or **My Capabilities** tabs.

## How to Use for Targeting & Outreach

### 1. My Capabilities / Keywords (Start Here)
- Edit or add to the list of keywords/phrases that describe what you offer (pre-loaded with defense manufacturing relevant terms like D38999, harness, backshell, IPC-A-620, MIL-STD, electro-mechanical, overmolding, potting, RG400, Glenair, crimp, avionics, etc.).
- These are used to **score every line item** in the budget for relevance to *you*.
- Click **Find Best Matches for My Capabilities** → get a ranked list of PEs/line items whose descriptions mention many of your keywords. Perfect for "combing through and targeting".
- Export the top ones to CSV for your CRM/outreach pipeline.

### 2. Keyword Search
- Enter keywords (supports simple AND by default; use Whoosh syntax for advanced: `+harness +connector +"D38999"`, phrases in quotes, fuzzy with `~`).
- Filter by component if indexed (DARPA, Navy, etc.).
- Results show:
  - PE number + Program Title (auto-extracted where possible)
  - Source document + page range
  - Highlighted snippets from the descriptive justification text
  - Expandable full relevant text
- For any promising result, click into **POC Research Helper**:
  - Auto-generates precise Google / LinkedIn / SBIR search queries tailored to that PE + title + your keywords.
  - One-click buttons to open those searches in your browser.
  - Direct links to SAM.gov opportunities search pre-filled with your keywords.
  - Guidance on next steps (check recent awards on USAspending.gov for that program, look for Industry Days, etc.).

### 3. Workflow Recommendation for Contractors
1. Update **My Capabilities** with your exact offerings (be specific: "D38999 Series III connectors", "overmolded harness assemblies for MIL-DTL-38999", "RG400 coax crimping per IPC-A-620", "custom backshells and strain relief for avionics").
2. Run **Best Matches for My Capabilities** across all indexed books.
3. Review top 10-20 hits. Read the justification snippets — they often say things like "develop custom interconnect solutions for next-gen platform" or "support cable harness integration and test".
4. For the best 3-5 matches, use the POC Research panel to generate outreach intel.
5. Prioritize: High funding + strong keyword overlap + recent activity (cross-check USAspending or news).
6. Outreach: Polite, capability-focused note referencing the specific program need you saw in the justification. Many PMs appreciate informed industry partners.

## Technical Notes & Limitations
- **PE / Line Item Detection**: Uses regex on common patterns in R-2/R-3 exhibits ("PE 060XXXXX", "Program Element (Number/Name)"). Works well on most modern justification books but not 100% perfect (some pages are pure tables or overviews). Unknown PEs still get indexed with their descriptive text — very usable.
- **Text Quality**: PDFs are official scanned/OCR'd sometimes; extraction is good with PyMuPDF but occasional weird line breaks or table bleed. Search still finds the good descriptive paragraphs.
- **No Direct Emails**: As noted, budget books don't publish per-PE POCs. The tool excels at *finding the right program to chase* and giving you ammunition for research.
- **Performance**: First index of a full FY set takes time/memory (depends on your machine). Subsequent searches are instant. Index lives in `whoosh_index/` next to the app or your chosen location.
- **Extensibility** (for devs):
  - Add semantic search by installing sentence-transformers + using embeddings on chunks (Chroma or FAISS backend easy to bolt on).
  - Add table parsing (camelot) to extract funding amounts per PE/project and filter by $ threshold.
  - Multi-FY support or incremental indexing.
  - Export to your CRM or Notion.
- **Legal/Ethics**: All data is public US Government budget material. Use for legitimate business development. Respect "no contact" lists if any programs have them. This is competitive intelligence, not classified.

## Example Starter Keywords (Defense Precision Mfg / Avionics / Interconnect)
See `app.py` for the default list — customize heavily for your shop (add your specific processes, materials, certifications, platforms you've supported like E-2, F-5, helo, shipboard, space payloads, etc.).

## Support & Roadmap
This is a practical tool built to solve a real pain point for small/medium defense contractors who don't have expensive GovWin or similar subscriptions. 

Roadmap ideas: 
- Semantic similarity ("find programs needing things *like* my overmolded harnesses").
- Auto-generate capability statement snippets tailored to a specific PE.
- Track which PEs you already contacted.
- Integration with your existing GitHub tools or ERP.

Pull requests or feedback welcome if you extend it.

**Built with**: Streamlit + PyMuPDF (fitz) + Whoosh. Pure local, no data leaves your machine.

Go find those funded programs and start the conversations. Good hunting! 

— For questions on the tool or customization for your specific manufacturing capabilities, reach out in the spirit of the SDVOSB community.