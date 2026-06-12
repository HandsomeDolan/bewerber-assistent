
## 2026-06-12 — Plan C first tailoring (smoke run)
- Firma: 2b AHEAD ThinkTank GmbH
- Rolle: Business AI Consultant (m/w/d) – KI Enablement & Kundenberatung
- Kontakt: Frau Moser, karriere@2bahead.com
- Posting source: Arbeitsagentur URL (direct jobdetail link)
- Output: Bewerbungsunterlagen/Bewerbungen/2026-06-12_2b-AHEAD-ThinkTank-GmbH_Business-AI-Consultant-...
- Mid-run fix: snapshot.py changed `wait_until="domcontentloaded"` → `"networkidle"` after first URL (search-results page) returned wrong content. Direct `/jobdetail/<id>` URL with networkidle returns full posting.
- Lebenslauf quality: berufsprofil reframed around KI-Automation/Low-Code/n8n; 8 relevant projects highlighted (BandScoring, n8n_builder, SEO-AFM etc.); skills top-5 matches job (Generative AI, Automatisierung, n8n, Supabase, Python); real metrics preserved (14→9 Tage, 16→10 Tage).
- Anschreiben quality: Anrede "Sehr geehrte Frau Moser" correct; konkrete Bezüge zu Aufgaben aus Posting (Use-Cases priorisieren, API-Anbindung, Enablement, Low-/No-Code); kein Buzzword-Overhead.
- Time: ~30s wall-clock (Snapshot + 2 LLM-Calls + PDF-Render).
