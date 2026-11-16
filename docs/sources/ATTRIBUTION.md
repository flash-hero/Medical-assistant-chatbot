# Attribution

Generated 2026-11-16 from the ACTIVE entries of `data_pipeline/sources/registry.yaml`. Do not edit by hand; change the registry and run `python -m data_pipeline report`.

Ausculta shows information from the sources below. Each answer cites its source; this page records the licence evidence and the credit line each publisher asks for. Images and logos are never used.

## Wave 1

### CDC web content (syndication API)

- Publisher: Centers for Disease Control and Prevention
- Credit line: Source: Centers for Disease Control and Prevention (CDC). Reference to specific commercial products or companies does not constitute endorsement by CDC, HHS or the U.S. Government. This material is available at no charge on cdc.gov.
- Licence: Public domain (U.S. Government work) with CDC use conditions (`us-gov-public-domain-cdc`); commercial use: conditional
- Licence evidence: https://www.cdc.gov/other/agencymaterials.html (verified 2026-11-15 by data-agent)
- Reuse mode: `quote_only` | trust tier 1 | languages: en
- Condition: Page text: most CDC and ATSDR information 'is not subject to copyright, is in the public domain, and may be freely used or reproduced without obtaining copyright permission'
- Condition: Requirement 1: attribute the agency ('Source: CDC'); requirement 2: show a non-endorsement disclaimer; requirement 3: 'You may not change the substantive content of the materials' (hence reuse_mode=quote_only); requirement 4: state that the material is otherwise available on the agency website for no charge
- Condition: Exceptions: resources and images made by contractors/grantees or licensed from third parties, and works of state and local governments, may be copyrighted; images are never ingested
- Condition: CDC, ATSDR and HHS logos are never used; content is taken from the CDC Content Syndication API (tools.cdc.gov/api/v2), the channel CDC offers for reuse of its pages
- Condition: Occupational (NIOSH) pages and non-English items are not ingested

### CDC Vaccine Information Statements

- Publisher: Centers for Disease Control and Prevention
- Credit line: Source: Centers for Disease Control and Prevention (CDC), Vaccine Information Statement. Reference to specific commercial products or companies does not constitute endorsement by CDC, HHS or the U.S. Government. This material is available at no charge on cdc.gov.
- Licence: Public domain (U.S. Government work) with CDC use conditions (`us-gov-public-domain-cdc`); commercial use: conditional
- Licence evidence: https://www.cdc.gov/other/agencymaterials.html (verified 2026-11-15 by data-agent)
- Reuse mode: `quote_only` | trust tier 1 | languages: en
- Condition: Same CDC terms as the cdc source: attribution, non-endorsement disclaimer, no change to substantive content (quote_only), statement that the material is free on cdc.gov
- Condition: VIS are produced by CDC under the National Childhood Vaccine Injury Act; only the current English HTML pages on www.cdc.gov are used (translations are hosted by Immunize.org and are not ingested)
- Condition: Images and logos are never ingested

### MedlinePlus Genetics

- Publisher: U.S. National Library of Medicine
- Credit line: Source: MedlinePlus, National Library of Medicine
- Licence: Public domain (U.S. Government work); acknowledge MedlinePlus (`public-domain-us-gov`); commercial use: yes
- Licence evidence: https://medlineplus.gov/about/using/usingcontent/ (verified 2026-11-15 by data-agent)
- Reuse mode: `paraphrase_ok` | trust tier 1 | languages: en
- Condition: Public-domain scope per the page: 'Summaries on Genetics pages, including health condition, gene, and chromosome pages and the Help Me Understand Genetics handbook' (English and Spanish)
- Condition: Acknowledge MedlinePlus with 'Courtesy of MedlinePlus from the National Library of Medicine' or 'Source: MedlinePlus, National Library of Medicine'
- Condition: Images and photos on Genetics pages may be copyrighted: images are never ingested
- Condition: The data are best interpreted using the labeling and context of the corresponding pages on the website (geneticsdatafilesapi page)
- Condition: db-key-list entries (SNOMED CT, ICD-10-CM, GTR...) are pointers only: only MeSH and OMIM identifiers are kept, as metadata, never as text

### MedlinePlus Health Topics

- Publisher: U.S. National Library of Medicine
- Credit line: Source: MedlinePlus, National Library of Medicine
- Licence: Public domain (U.S. Government work); acknowledge MedlinePlus (`public-domain-us-gov`); commercial use: yes
- Licence evidence: https://medlineplus.gov/about/using/usingcontent/ (verified 2026-11-15 by data-agent)
- Reuse mode: `paraphrase_ok` | trust tier 1 | languages: en
- Condition: Public-domain scope per the page: homepage, summaries on health topic pages, medical test information, Genetics summaries, watermarked illustrations, recipes, videos, tutorials
- Condition: Acknowledge MedlinePlus with 'Courtesy of MedlinePlus from the National Library of Medicine' or 'Source: MedlinePlus, National Library of Medicine'
- Condition: A.D.A.M. Medical Encyclopedia and ASHP drug monographs are copyrighted: never ingest (medlineplus.gov/ency/, medlineplus.gov/druginfo/)
- Condition: Images and photos may be copyrighted: images are never ingested
- Condition: Do not use the NLM logo; do not frame or masquerade MedlinePlus URLs as another domain; RSS feeds are personal use only
- Condition: xml.html: the XML files are offered for download and use; indicate that the information is from MedlinePlus.gov

### NCI PDQ cancer information summaries (patient version)

- Publisher: National Cancer Institute (NIH)
- Credit line: Source: National Cancer Institute (NCI), PDQ Cancer Information Summaries (Patient Version), cancer.gov
- Licence: Text free of copyright (NCI Reuse of NCI Information); credit NCI (`us-gov-free-of-copyright-nci`); commercial use: conditional
- Licence evidence: https://www.cancer.gov/policies/copyright-reuse (verified 2026-11-15 by data-agent)
- Reuse mode: `paraphrase_ok` | trust tier 1 | languages: en
- Condition: Page text: 'Unless otherwise indicated, all text within National Cancer Institute (NCI) products is free of copyright and may be reused without our permission. Credit the National Cancer Institute as the source.'
- Condition: Digital reproduction: link to the original NCI product using its original title (citations carry the page URL and title)
- Condition: Graphics may be copyrighted by third parties: images are never ingested
- Condition: The NCI logo and the PDQ trademark may only be used in reproductions of original, wholly unchanged NCI products: the NCI logo is never used and excerpts must not be presented as an NCI PDQ summary
- Condition: Commercial use is not addressed explicitly on the page ('free of copyright ... without our permission'); recorded as conditional
- Condition: Only patient-version PDQ summaries (types/*/patient/*-pdq) are ingested; health-professional versions, Spanish pages and the 'About This PDQ Summary' section are not

### NIDDK health information

- Publisher: National Institute of Diabetes and Digestive and Kidney Diseases (NIH)
- Credit line: Source: National Institute of Diabetes and Digestive and Kidney Diseases (NIDDK), National Institutes of Health
- Licence: Copyright free (NIDDK copyright notice); acknowledge NIDDK (`us-gov-copyright-free-niddk`); commercial use: conditional
- Licence evidence: https://www.niddk.nih.gov/copyright (verified 2026-11-15 by data-agent)
- Reuse mode: `paraphrase_ok` | trust tier 1 | languages: en
- Condition: Page text: 'The majority of information on this site is copyright free and can be freely downloaded and reproduced. Content reproduced without changes should acknowledge the National Institute of Diabetes and Digestive and Kidney Diseases (NIDDK) as the source.'
- Condition: Exceptions: documents co-sponsored with private organisations (other parties may retain rights) and graphics licensed from third parties; images and logos are never ingested; pages carrying their own copyright statement are dropped by the quality gates
- Condition: Edited content: NIDDK and NIH logos must be removed; content must not be used to imply endorsement of any company, product or service, or to recommend specific medical advice, treatments or referrals
- Condition: Commercial use is not addressed explicitly on the page ('copyright free'); recorded as conditional
- Condition: robots.txt Crawl-delay: 10 seconds is honoured; the sitemap is https://www.niddk.nih.gov/sitemap-sc.xml

### openFDA drug labels (SPL)

- Publisher: U.S. Food and Drug Administration
- Credit line: Data provided by the U.S. Food and Drug Administration (https://open.fda.gov)
- Licence: Public domain, CC0 1.0 Universal dedication (FDA openFDA Terms of Service) (`CC0-1.0`); commercial use: yes
- Licence evidence: https://open.fda.gov/terms/ (verified 2026-11-15 by data-agent)
- Reuse mode: `paraphrase_ok` | trust tier 1 | languages: en
- Condition: Terms: content and data on openFDA are public domain under CC0 1.0 'unless otherwise noted'; commercial use allowed without permission
- Condition: Attribution is requested, not required; the example citation is used as the attribution line
- Condition: Works where CC0 does not apply are 'clearly marked by a warning'; the drug label download carries no such marking (download.json meta: disclaimer, terms, license only); documents containing 'not in the public domain' or 'third party copy rights may apply' are dropped
- Condition: The GMDN Agency notice (no AI-training use without licence) applies to device GMDN term data only; no device data is fetched
- Condition: openFDA data are unvalidated and must not be relied on for medical care decisions (download.json disclaimer): labels carry jurisdiction 'US FDA label'
- Condition: Right to Limit: access may be restricted if limits are circumvented; downloads use the published bulk partitions at 1 request/second

## Wave 2

### NCCIH health information

- Publisher: National Center for Complementary and Integrative Health (NIH)
- Credit line: Source: National Center for Complementary and Integrative Health (NCCIH), National Institutes of Health
- Licence: Public domain (NCCIH Website Information and Policies); credit NCCIH (`us-gov-public-domain-nccih`); commercial use: conditional
- Licence evidence: https://www.nccih.nih.gov/tools/privacy (verified 2026-11-15 by data-agent)
- Reuse mode: `paraphrase_ok` | trust tier 1 | languages: en
- Condition: Page text: 'Text on the NCCIH website is not copyrighted and is in the public domain. You may print and copy our publications. Please credit the National Center for Complementary and Integrative Health as the source, and include the publication title and date, where applicable. Do not use our information in a way that suggests we endorse any commercial product or service.'
- Condition: The site may host copyrighted documents (e.g. full-text journal articles) and purchased photos/graphics: images are never ingested
- Condition: Commercial use is not addressed explicitly; recorded as conditional

### NEI eye health information

- Publisher: National Eye Institute (NIH)
- Credit line: Courtesy: National Eye Institute, National Institutes of Health (NEI/NIH)
- Licence: Public domain (NEI Copyright Policy); courtesy credit requested (`us-gov-public-domain-nei`); commercial use: conditional
- Licence evidence: https://www.nei.nih.gov/web-policies/copyright-policy (verified 2026-11-15 by data-agent)
- Reuse mode: `paraphrase_ok` | trust tier 1 | languages: en
- Condition: Page text: 'Unless otherwise noted, information on the National Eye Institute website is in the public domain. Public domain information may be freely distributed and copied, but, as a courtesy, we request that the National Eye Institute be given an appropriate acknowledgement'
- Condition: Documents, illustrations and photographs licensed from private parties may be copyrighted: images are never ingested; NEI logos are never used
- Condition: Commercial use is not addressed explicitly; recorded as conditional

### NHLBI health information

- Publisher: National Heart, Lung, and Blood Institute (NIH)
- Credit line: Source: National Heart, Lung, and Blood Institute (NHLBI), National Institutes of Health, HHS
- Licence: Public domain (NHLBI website policy), content to be used unchanged (`us-gov-public-domain-nhlbi`); commercial use: conditional
- Licence evidence: https://www.nhlbi.nih.gov/about/contact/trademark-branding-and-logo (verified 2026-11-15 by data-agent)
- Reuse mode: `quote_only` | trust tier 1 | languages: en
- Condition: Page text: 'Most of the information on the NHLBI website is in the public domain and can be used without restriction. The NHLBI asks only that no changes be made to the publications, videos, images, or other formatted multimedia products and that the material, as well any NHLBI webpage links, not be used in any direct or indirect product endorsement or advertising.' Treated conservatively as quote_only
- Condition: Some images are licensed from third parties and restricted; images and logos are never ingested; pages with their own copyright statement are dropped
- Condition: Commercial use is not addressed explicitly; recorded as conditional, with no product endorsement or advertising use

### NIAMS health topics

- Publisher: National Institute of Arthritis and Musculoskeletal and Skin Diseases (NIH)
- Credit line: Source: National Institute of Arthritis and Musculoskeletal and Skin Diseases (NIAMS), National Institutes of Health
- Licence: Public domain (NIAMS Disclaimer page); credit NIAMS (`us-gov-public-domain-niams`); commercial use: conditional
- Licence evidence: https://www.niams.nih.gov/disclaimer (verified 2026-11-15 by data-agent)
- Reuse mode: `paraphrase_ok` | trust tier 1 | languages: en
- Condition: Page text: 'The text you find on this site is in the public domain. You may use and reproduce text material you find on this website.'
- Condition: Many photographs and illustrations were purchased from other sources and are copyrighted: images are never ingested
- Condition: robots.txt disallows GPTBot, CCbot, anthropic-ai, Claude-Web and Google-Extended entirely; AuscultaBot is not listed and robots.txt is respected, but the owner should confirm the NIAMS stance on AI use before indexing this source
- Condition: Commercial use is not addressed explicitly; recorded as conditional

### NICHD health topics

- Publisher: Eunice Kennedy Shriver National Institute of Child Health and Human Development (NIH)
- Credit line: Courtesy: Eunice Kennedy Shriver National Institute of Child Health and Human Development
- Licence: Public domain (NICHD website disclaimer, Copyright and Reuse); credit NICHD (`us-gov-public-domain-nichd`); commercial use: conditional
- Licence evidence: https://www.nichd.nih.gov/disclaimer (verified 2026-11-15 by data-agent)
- Reuse mode: `paraphrase_ok` | trust tier 1 | languages: en
- Condition: Page text: 'Most text appearing on the NICHD website has been either prepared by employees of the U.S. government as part of their official duties or prepared under contracts for NICHD. In both instances, the text is in the public domain and not subject to copyright... You may freely copy that material and credit NICHD'
- Condition: Some documents (for example full-text journal articles) are copyright-protected; logos, photos and illustrations must not be reused without permission: images and logos are never ingested
- Condition: Commercial use is not addressed explicitly; recorded as conditional

### NIMH health information

- Publisher: National Institute of Mental Health (NIH)
- Credit line: Source: National Institute of Mental Health (NIMH), National Institutes of Health
- Licence: Public domain (NIMH Copyright Policy); cite NIMH (`us-gov-public-domain-nimh`); commercial use: conditional
- Licence evidence: https://www.nimh.nih.gov/site-info/policies (verified 2026-11-15 by data-agent)
- Reuse mode: `paraphrase_ok` | trust tier 1 | languages: en
- Condition: Page text: 'The information on our website and in our materials is in the public domain. You may copy and reuse it without permission.'
- Condition: Modifications: 'You can edit or reformat the copied text, but you cannot change it in a way that is misleading or inaccurate.' Attribution: 'please cite the National Institute of Mental Health as the source.'
- Condition: Images: the page excludes reuse of website photos and publication images ('You may not reuse or copy any of the publication images'): images are never ingested
- Condition: Commercial use is not addressed explicitly; recorded as conditional. Do not use the NIMH logo or imply endorsement

