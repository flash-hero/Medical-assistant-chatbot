# Manual audit sample

Generated 2026-11-16 by `python -m data_pipeline report` (seed 20261115). 200 documents drawn from 15,971 normalised documents, stratified by source.

For each entry the auditor decides whether the text is a clean, correct health-information document (readable, on topic, no navigation or advertising text, no personal data, no instructions aimed at an AI) and records the result in the checklist below. The automated checks are a pre-filter, not the audit.
Automated pre-check: 195 of 200 pass all automated checks. `data.manual_audit_clean` (target 0.97) is **not run** by the data agent.

## 1. 2008 Adult Asthma Data: Prevalence Tables and Maps

- source: `cdc` | language: `en` | audience: `patient` | licence: `us-gov-public-domain-cdc` | reuse: `quote_only`
- URL: https://www.cdc.gov/asthma/brfss/08/lifetime/tableL6.htm
- doc_id: `cdc:126740` | sections: 1
- automated checks: all pass
- first 300 characters: State \| Education \| Sample Size \| Prevalence (percent) \| Standard Error \| 95% CI\* (percent) \| \|\| \|\| \|\| \| Prevalence (number) \| 95% CI\* (number) U.S. Total\*\* \| HS Nongrad \| 39,063 \| 14.1 \| 0.39 \| (13.4 – 14.9) \| \|\| \| 3,675,074 \| (3,463,932 – 3,886,216) U.S. Total\*\* \| HS
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 2. 2008 Child Asthma Data: Prevalence Tables

- source: `cdc` | language: `en` | audience: `patient` | licence: `us-gov-public-domain-cdc` | reuse: `quote_only`
- URL: https://www.cdc.gov/asthma/brfss/08/child/current/tableC4.htm
- doc_id: `cdc:126761` | sections: 1
- automated checks: all pass
- first 300 characters: State \| Race \| Sample Size \| Prevalence (Percent) \| Standard Error \| 95% CI\* (Percent) \| Prevalence (Number) \| 95% CI\* (Number) Total \*\* \| White \| 58,693 \| 7.8 \| 0.20 \| (7.4 – 8.2) \| 3,097,794 \| (2,942,839 – 3,252,748) Total \*\* \| Black \| 6,454 \| 15.7 \| 0.82 \| (14.2 – 17.4) \
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 3. Identify Buildings with Increased Legionella Risk

- source: `cdc` | language: `en` | audience: `professional` | licence: `us-gov-public-domain-cdc` | reuse: `quote_only`
- URL: https://www.cdc.gov/control-legionella/php/toolkit/wmp-worksheet.html
- doc_id: `cdc:730432` | sections: 5
- automated checks: all pass
- first 300 characters: - Quickly assess the need for a water management program (WMP). - Answer the first 4 questions for buildings and the last 4 questions for devices. - Effective WMPs can reduce the risk of Legionella growing and spreading. - This worksheet supplements CDC's Legionella WMP toolkit. The Legionella WMP t
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 4. AGE Monitoring

- source: `cdc` | language: `en` | audience: `professional` | licence: `us-gov-public-domain-cdc` | reuse: `quote_only`
- URL: https://www.cdc.gov/vessel-sanitation/php/our-role/monitoring.html
- doc_id: `cdc:309467` | sections: 5
- automated checks: all pass
- first 300 characters: We track cases of acute gastroenteritis (AGE) on cruise ships under our jurisdiction. AGE is a type of gastrointestinal (GI) illness. Common symptoms include diarrhea, muscle ache, headache, abdominal pain, and fever. Our surveillance system tracks cases of acute gastroenteritis (AGE) on cruise ship
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 5. Clinical Overview of Botulism

- source: `cdc` | language: `en` | audience: `professional` | licence: `us-gov-public-domain-cdc` | reuse: `quote_only`
- URL: https://www.cdc.gov/botulism/hcp/clinical-overview/index.html
- doc_id: `cdc:273489` | sections: 16
- automated checks: all pass
- first 300 characters: - Initial diagnosis of botulism is based on clinical symptoms. - Consultation is available for suspected cases. - If clinical consultation supports botulism, begin treatment as soon as possible. Do not wait for laboratory confirmation. - Botulism is a notifiable disease. All suspected cases must be 
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 6. About Vibrio Infection

- source: `cdc` | language: `en` | audience: `patient` | licence: `us-gov-public-domain-cdc` | reuse: `quote_only`
- URL: https://www.cdc.gov/vibrio/about/index.html
- doc_id: `cdc:402214` | sections: 14
- automated checks: all pass
- first 300 characters: - Vibrio are bacteria that naturally live in coastal waters. - About a dozen kinds of Vibrio can cause people to get an infection called vibriosis. - People can get vibriosis after swallowing Vibrio or getting it in a wound. - Vibrio infection can be serious. Know when to seek medical care. Vibrio a
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 7. About Mumps

- source: `cdc` | language: `en` | audience: `patient` | licence: `us-gov-public-domain-cdc` | reuse: `quote_only`
- URL: https://www.cdc.gov/mumps/about/index.html
- doc_id: `cdc:306713` | sections: 8
- automated checks: all pass
- first 300 characters: - Mumps is a contagious viral infection that can be serious. - Common symptoms include painful swelling of the jaw, fever, tiredness, appetite loss, and headache. - Get vaccinated for mumps with the MMR vaccine, especially before travelling internationally. Mumps is a contagious disease caused by a 
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 8. Tuberculosis

- source: `cdc` | language: `en` | audience: `professional` | licence: `us-gov-public-domain-cdc` | reuse: `quote_only`
- URL: https://www.cdc.gov/immigrant-refugee-health/hcp/domestic-guidance/tuberculosis.html
- doc_id: `cdc:245257` | sections: 19
- automated checks: all pass
- first 300 characters: The domestic medical screening guidance is for state public health departments and healthcare providers in the United States who conduct the initial medical screening for refugees. These screenings usually occur 30-90 days after the refugees arrive in the United States. This guidance aims to promote
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 9. Sexually Transmitted Diseases (STD)

- source: `cdc` | language: `en` | audience: `patient` | licence: `us-gov-public-domain-cdc` | reuse: `quote_only`
- URL: https://www.cdc.gov/nchs/fastats/stds.htm
- doc_id: `cdc:224526` | sections: 3
- automated checks: all pass
- first 300 characters: Data are for the U.S. - Number of new syphilis cases: 129,813 (2019) - Number of new chlamydia cases: 1,808,703 (2019) - Number of new gonorrhea cases: 616,392 (2019) Source: Health, United States, 2020-2021, Table IDNotif \[PDF – 9.8 MB\] - AIDS/HIV - Viral Hepatitis - Key Statistics from the Natio
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 10. Great American Smokeout: Make Today Your Quit Day!

- source: `cdc` | language: `en` | audience: `patient` | licence: `us-gov-public-domain-cdc` | reuse: `quote_only`
- URL: https://www.cdc.gov/tobacco/tobacco-features/the-great-american-smokeout.html
- doc_id: `cdc:433834` | sections: 10
- automated checks: all pass
- first 300 characters: Quitting smoking is one of the most important steps you can take to improve your health. Join the Great American Smokeout and make today your quit day! Are you ready to quit smoking? Quitting smoking improves your health, but it can be hard to do. You don't have to do it alone! On November 21, pleas
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 11. Type 2 Diabetes and Your Liver

- source: `cdc` | language: `en` | audience: `patient` | licence: `us-gov-public-domain-cdc` | reuse: `quote_only`
- URL: https://www.cdc.gov/diabetes/diabetes-complications/type-2-diabetes-liver-disease.html
- doc_id: `cdc:737813` | sections: 6
- automated checks: all pass
- first 300 characters: - Did you know that type 2 diabetes and overweight can increase your risk for liver disease? - Learn more about this connection and how to care for your liver. Your liver is the largest internal organ in your body, and it's responsible for many vital functions, including: - Filtering your blood to r
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 12. Preventing Drowning

- source: `cdc` | language: `en` | audience: `patient` | licence: `us-gov-public-domain-cdc` | reuse: `quote_only`
- URL: https://www.cdc.gov/drowning/prevention/index.html
- doc_id: `cdc:514641` | sections: 15
- automated checks: all pass
- first 300 characters: - More children ages 1–4 die from drowning than any other cause of death. - Drowning happens in seconds and is often silent. - Drowning can happen to anyone, any time there is access to water. Formal swimming lessons can reduce the risk of drowning. 12345Children who have had swimming lessons still 
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 13. CDC in Malawi

- source: `cdc` | language: `en` | audience: `patient` | licence: `us-gov-public-domain-cdc` | reuse: `quote_only`
- URL: https://www.cdc.gov/global-health/countries/malawi.html
- doc_id: `cdc:125294` | sections: 13
- automated checks: all pass
- first 300 characters: CDC established an office in Malawi in 2001. CDC Malawi works closely with the Government of Malawi and partner organizations to prevent, detect, respond to, and control HIV and other infectious disease outbreaks. CDC’s work aims to protect the health of Americans and promote public health around th
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 14. Preventing Chikungunya

- source: `cdc` | language: `en` | audience: `patient` | licence: `us-gov-public-domain-cdc` | reuse: `quote_only`
- URL: https://www.cdc.gov/chikungunya/prevention/index.html
- doc_id: `cdc:264159` | sections: 4
- automated checks: all pass
- first 300 characters: - Chikungunya virus is spread through the bite of an infected mosquito. - The best way to protect yourself from chikungunya is to prevent mosquito bites and get vaccinated before traveling, if recommended. - The most recent locally acquired case was reported from a U.S. state in 2025. Chikungunya vi
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 15. Meningococcal Disease and People Receiving Complement Inhibitors

- source: `cdc` | language: `en` | audience: `patient` | licence: `us-gov-public-domain-cdc` | reuse: `quote_only`
- URL: https://www.cdc.gov/meningococcal/risk-factors/receiving-complement-inhibitors.html
- doc_id: `cdc:332758` | sections: 9
- automated checks: all pass
- first 300 characters: - Receiving a complement inhibitor greatly increases someone's risk of meningococcal disease. - Getting vaccinated and taking antibiotics offers some (but not complete) protection. - People receiving complement inhibitors should seek treatment quickly for symptoms of meningococcal disease. - Be awar
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 16. CDC in Lesotho

- source: `cdc` | language: `en` | audience: `patient` | licence: `us-gov-public-domain-cdc` | reuse: `quote_only`
- URL: https://www.cdc.gov/global-health/countries/lesotho.html
- doc_id: `cdc:125242` | sections: 11
- automated checks: all pass
- first 300 characters: CDC established an office in Lesotho in 2007 and collaborates with the Lesotho Ministry of Health (MOH) and partners to build and strengthen the country’s core public health capabilities. Under the U.S. President’s Emergency Plan for AIDS Relief (PEPFAR), CDC’s work in Lesotho focuses on HIV prevent
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 17. STOP Program

- source: `cdc` | language: `en` | audience: `patient` | licence: `us-gov-public-domain-cdc` | reuse: `quote_only`
- URL: https://www.cdc.gov/global-immunization/stop/index.html
- doc_id: `cdc:729341` | sections: 4
- automated checks: all pass
- first 300 characters: The STOP Program is a collaboration between CDC, the United Nations Children's Fund (UNICEF) and the African Field Epidemiology Network (AFENET) to train international public health consultants to deploy to countries worldwide. STOP consultants help strengthen national immunization surveillance prog
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 18. Dialysis Component Training

- source: `cdc` | language: `en` | audience: `patient` | licence: `us-gov-public-domain-cdc` | reuse: `quote_only`
- URL: https://www.cdc.gov/nhsn/training/dialysis/index.html
- doc_id: `cdc:128540` | sections: 3
- automated checks: all pass
- first 300 characters: - Dialysis Event Surveillance Annual Training Course and Post-Assessment \[CBT – 60mins\] - WB4638 Continuing Education Information \[PDF – 247 KB\] - When and How to Correct or Delete a Reported Event – September 2025 - Slideset \[PDF – 228 MB\] Introduction to the New Dialysis Facility Type – Sept
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 19. How Zika Spreads

- source: `cdc` | language: `en` | audience: `patient` | licence: `us-gov-public-domain-cdc` | reuse: `quote_only`
- URL: https://www.cdc.gov/zika/causes/index.html
- doc_id: `cdc:353723` | sections: 12
- automated checks: all pass
- first 300 characters: - Zika virus is spread mostly by the bite of an infected Aedes species mosquito. - Zika virus can spread from a pregnant woman to her fetus. Infection during pregnancy can cause certain birth defects. - Zika virus can spread through sex. Condoms can reduce the chance of getting Zika virus from sex. 
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 20. Respiratory Infections and Asthma

- source: `cdc` | language: `en` | audience: `patient` | licence: `us-gov-public-domain-cdc` | reuse: `quote_only`
- URL: https://www.cdc.gov/asthma/respiratory-infections/index.html
- doc_id: `cdc:405289` | sections: 10
- automated checks: all pass
- first 300 characters: - Respiratory infections like influenza (flu), coronavirus disease 2019 (COVID-19), and RSV, or Respiratory Syncytial Virus, can be more serious for individuals with asthma because they can lead to pneumonia and asthma attacks. - Get vaccinated for respiratory diseases when vaccines are available an
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 21. Young Children: Safety in the Home & Community

- source: `cdc` | language: `en` | audience: `patient` | licence: `us-gov-public-domain-cdc` | reuse: `quote_only`
- URL: https://www.cdc.gov/parents/children/safety-in-the-home-and-community.html
- doc_id: `cdc:229716` | sections: 2
- automated checks: all pass
- first 300 characters: You play an important role in keeping your child safe. We have information and tools to help protect your child from injuries and violence. - Carbon Monoxide Poisoning - Child Abuse and Neglect - Child Passenger Safety - Childcare: Exposure to Environmental Contamination - Childcare: Safe Places - C
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 22. Yellow Fever Vaccine VIS

- source: `cdc_vis` | language: `en` | audience: `patient` | licence: `us-gov-public-domain-cdc` | reuse: `quote_only`
- URL: https://www.cdc.gov/vaccines/hcp/current-vis/yellow-fever.html
- doc_id: `cdc_vis:yellow-fever` | sections: 9
- automated checks: all pass
- first 300 characters: Yellow Fever Vaccine: What You Need to Know Apr. 1, 2020 Current edition: April 1, 2020 Yellow fever vaccine can prevent yellow fever. Yellow fever is a serious disease caused by the yellow fever virus. There is no medicine to treat or cure yellow fever. Yellow fever virus is spread by the bite of a
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 23. 3-hydroxy-3-methylglutaryl-CoA lyase deficiency

- source: `medlineplus_genetics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/genetics/condition/3-hydroxy-3-methylglutaryl-coa-lyase-deficiency
- doc_id: `medlineplus_genetics:condition-20467` | sections: 3
- automated checks: all pass
- first 300 characters: 3-hydroxy-3-methylglutaryl-CoA lyase deficiency (also known as HMG-CoA lyase deficiency) is an uncommon inherited disorder in which the body cannot process a particular protein building block (amino acid) called leucine. Additionally, the disorder prevents the body from making ketones, which are com
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 24. 3MC syndrome

- source: `medlineplus_genetics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/genetics/condition/3mc-syndrome
- doc_id: `medlineplus_genetics:condition-20950` | sections: 3
- automated checks: all pass
- first 300 characters: 3MC syndrome is a disorder characterized by unusual facial features and problems affecting other tissues and organs. The distinctive facial features of people with 3MC syndrome include widely spaced eyes (hypertelorism), a narrowing of the eye opening (blepharophimosis), droopy eyelids (ptosis), hig
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 25. Autoimmune Addison disease

- source: `medlineplus_genetics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/genetics/condition/autoimmune-addison-disease
- doc_id: `medlineplus_genetics:condition-21176` | sections: 3
- automated checks: all pass
- first 300 characters: Autoimmune Addison disease affects the function of the adrenal glands, which are small hormone-producing glands located on top of each kidney. It is classified as an autoimmune disorder because it results from a malfunctioning immune system that attacks the adrenal glands. As a result, the productio
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 26. Congenital hyperinsulinism

- source: `medlineplus_genetics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/genetics/condition/congenital-hyperinsulinism
- doc_id: `medlineplus_genetics:condition-20892` | sections: 3
- automated checks: all pass
- first 300 characters: Congenital hyperinsulinism is a condition that causes individuals to have abnormally high levels of insulin. Insulin is a hormone that helps control levels of blood glucose, also called blood sugar. People with this condition have frequent episodes of low blood glucose (hypoglycemia). In infants and
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 27. Familial exudative vitreoretinopathy

- source: `medlineplus_genetics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/genetics/condition/familial-exudative-vitreoretinopathy
- doc_id: `medlineplus_genetics:condition-20718` | sections: 3
- automated checks: all pass
- first 300 characters: Familial exudative vitreoretinopathy is a hereditary disorder that can cause vision loss that worsens over time. This condition affects the retina, the specialized light-sensitive tissue that lines the back of the eye. In people with this disorder, blood vessels do not fully develop at the outer edg
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 28. Focal dermal hypoplasia

- source: `medlineplus_genetics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/genetics/condition/focal-dermal-hypoplasia
- doc_id: `medlineplus_genetics:condition-20755` | sections: 3
- automated checks: all pass
- first 300 characters: Focal dermal hypoplasia is a genetic disorder that primarily affects the skin, skeleton, eyes, and face. About 90 percent of affected individuals are female. Males usually have milder signs and symptoms than females. Although intelligence is typically unaffected, some individuals have intellectual d
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 29. Gorlin syndrome

- source: `medlineplus_genetics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/genetics/condition/gorlin-syndrome
- doc_id: `medlineplus_genetics:condition-20432` | sections: 3
- automated checks: all pass
- first 300 characters: Gorlin syndrome, also known as nevoid basal cell carcinoma syndrome, is a condition that affects many areas of the body and increases the risk of developing various cancerous and noncancerous tumors. In people with Gorlin syndrome, the type of cancer diagnosed most often is basal cell carcinoma, whi
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 30. Hypomyelination and congenital cataract

- source: `medlineplus_genetics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/genetics/condition/hypomyelination-and-congenital-cataract
- doc_id: `medlineplus_genetics:condition-20803` | sections: 3
- automated checks: all pass
- first 300 characters: Hypomyelination and congenital cataract is an inherited condition that affects the nervous system and the eyes. This disease is one of a group of genetic disorders called leukoencephalopathies. Leukoencephalopathies involve abnormalities of the brain's white matter. White matter consists of nerve fi
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 31. Isolated sulfite oxidase deficiency

- source: `medlineplus_genetics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/genetics/condition/isolated-sulfite-oxidase-deficiency
- doc_id: `medlineplus_genetics:condition-21350` | sections: 3
- automated checks: all pass
- first 300 characters: Isolated sulfite oxidase deficiency (ISOD) is a disorder of the nervous system, with a severe "classic" form that starts in the newborn period and a milder, late-onset form that begins later in infancy or early childhood. Classic ISOD appears within the first few days after birth with signs and symp
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 32. Long-chain 3-hydroxyacyl-CoA dehydrogenase deficiency

- source: `medlineplus_genetics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/genetics/condition/long-chain-3-hydroxyacyl-coa-dehydrogenase-deficiency
- doc_id: `medlineplus_genetics:condition-20407` | sections: 3
- automated checks: all pass
- first 300 characters: Long-chain 3-hydroxyacyl-CoA dehydrogenase (LCHAD) deficiency is a rare condition that prevents the body from converting certain fats to energy, particularly during periods without food (fasting). Signs and symptoms of LCHAD deficiency typically appear during infancy or early childhood. Many affecte
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 33. Maternally inherited diabetes and deafness

- source: `medlineplus_genetics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/genetics/condition/maternally-inherited-diabetes-and-deafness
- doc_id: `medlineplus_genetics:condition-21357` | sections: 3
- automated checks: all pass
- first 300 characters: Maternally inherited diabetes and deafness (MIDD) is a form of diabetes that is often accompanied by hearing loss, especially of high tones. The diabetes in MIDD is characterized by high blood sugar (glucose) levels, known as hyperglycemia. This results from a shortage of the hormone insulin, which 
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 34. Mosaic variegated aneuploidy syndrome

- source: `medlineplus_genetics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/genetics/condition/mosaic-variegated-aneuploidy-syndrome
- doc_id: `medlineplus_genetics:condition-21217` | sections: 3
- automated checks: all pass
- first 300 characters: Mosaic variegated aneuploidy (MVA) syndrome is a rare disorder in which some cells in the body have an abnormal number of chromosomes instead of the usual 46 chromosomes, a situation known as aneuploidy. Most commonly, cells have an extra chromosome, which is called trisomy, or are missing a chromos
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 35. Mucolipidosis II alpha/beta

- source: `medlineplus_genetics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/genetics/condition/mucolipidosis-ii-alpha-beta
- doc_id: `medlineplus_genetics:condition-20763` | sections: 3
- automated checks: all pass
- first 300 characters: Mucolipidosis II alpha/beta (also known as I-cell disease) is a progressively debilitating disorder that affects many parts of the body. Most affected individuals do not survive past early childhood. At birth, children with mucolipidosis II alpha/beta are small and have weak muscle tone (hypotonia) 
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 36. Myostatin-related muscle hypertrophy

- source: `medlineplus_genetics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/genetics/condition/myostatin-related-muscle-hypertrophy
- doc_id: `medlineplus_genetics:condition-20714` | sections: 3
- automated checks: all pass
- first 300 characters: Myostatin-related muscle hypertrophy is a rare condition characterized by reduced body fat and increased muscle size. Affected individuals have up to twice the usual amount of muscle mass in their bodies. They also tend to have increased muscle strength. Myostatin-related muscle hypertrophy is not k
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 37. Oculofaciocardiodental syndrome

- source: `medlineplus_genetics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/genetics/condition/oculofaciocardiodental-syndrome
- doc_id: `medlineplus_genetics:condition-20372` | sections: 3
- automated checks: all pass
- first 300 characters: Oculofaciocardiodental (OFCD) syndrome is a condition that affects the development of the eyes (oculo-), facial features (facio-), heart (cardio-), and teeth (dental). The eye abnormalities associated with OFCD syndrome can affect one or both eyes. Many people with this condition are born with eyeba
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 38. Osteopetrosis

- source: `medlineplus_genetics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/genetics/condition/osteopetrosis
- doc_id: `medlineplus_genetics:condition-20835` | sections: 3
- automated checks: all pass
- first 300 characters: Osteopetrosis is a bone disease that makes bone tissue abnormally compact and dense and also prone to breakage (fracture). Researchers have described several major types of osteopetrosis, which are usually distinguished by their pattern of inheritance: autosomal dominant or autosomal recessive. The 
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 39. Periventricular heterotopia

- source: `medlineplus_genetics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/genetics/condition/periventricular-heterotopia
- doc_id: `medlineplus_genetics:condition-20683` | sections: 3
- automated checks: all pass
- first 300 characters: Periventricular heterotopia is a condition in which nerve cells (neurons) do not migrate properly during the early development of the fetal brain, from about the 6th week to the 24th week of pregnancy. Heterotopia means "out of place." In normal brain development, neurons form in the periventricular
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 40. Progressive pseudorheumatoid dysplasia

- source: `medlineplus_genetics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/genetics/condition/progressive-pseudorheumatoid-dysplasia
- doc_id: `medlineplus_genetics:condition-21538` | sections: 3
- automated checks: all pass
- first 300 characters: Progressive pseudorheumatoid dysplasia (PPRD) is a joint disease that worsens over time. This condition is characterized by breakdown (degeneration) of the cartilage between bones (articular cartilage). This cartilage covers and protects the ends of bones, and its degeneration leads to pain and stif
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 41. Rabson-Mendenhall syndrome

- source: `medlineplus_genetics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/genetics/condition/rabson-mendenhall-syndrome
- doc_id: `medlineplus_genetics:condition-21383` | sections: 3
- automated checks: all pass
- first 300 characters: Rabson-Mendenhall syndrome is a rare disorder characterized by severe insulin resistance, a condition in which the body's tissues and organs do not respond properly to the hormone insulin. Insulin normally helps regulate blood sugar levels by controlling how much sugar (in the form of glucose) is pa
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 42. AVPR2 gene (arginine vasopressin receptor 2)

- source: `medlineplus_genetics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/genetics/gene/avpr2
- doc_id: `medlineplus_genetics:gene-22072` | sections: 2
- automated checks: all pass
- first 300 characters: The AVPR2 gene provides instructions for making a protein known as the vasopressin V2 receptor. This receptor works together with a hormone called arginine vasopressin (AVP), which is sometimes also called antidiuretic hormone (ADH). The vasopressin V2 receptor is found in the kidneys in structures 
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 43. CPT2 gene (carnitine palmitoyltransferase 2)

- source: `medlineplus_genetics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/genetics/gene/cpt2
- doc_id: `medlineplus_genetics:gene-21701` | sections: 2
- automated checks: all pass
- first 300 characters: The CPT2 gene provides instructions for making an enzyme called carnitine palmitoyltransferase 2. This enzyme is essential for fatty acid oxidation, a multistep process that breaks down (metabolizes) fats and converts them into energy. Fatty acids are a major source of energy for the heart and muscl
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 44. CTNND2 gene (catenin delta 2)

- source: `medlineplus_genetics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/genetics/gene/ctnnd2
- doc_id: `medlineplus_genetics:gene-22603` | sections: 2
- automated checks: all pass
- first 300 characters: The CTNND2 gene provides instructions for making a protein called delta-catenin. This protein is active in the nervous system, where it likely helps cells stick together (cell adhesion) and plays a role in cell movement. In the developing brain, it may help guide nerve cells to their proper position
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 45. DCAF17 gene (DDB1 and CUL4 associated factor 17)

- source: `medlineplus_genetics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/genetics/gene/dcaf17
- doc_id: `medlineplus_genetics:gene-23085` | sections: 2
- automated checks: all pass
- first 300 characters: The DCAF17 gene provides instructions for making a protein whose function is unknown. The gene is active (expressed) in several organs and tissues in the body, including the brain, skin, and liver. Within cells, the protein produced from this gene is found in the nucleolus, which is a small region i
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 46. FERMT1 gene (FERM domain containing kindlin 1)

- source: `medlineplus_genetics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/genetics/gene/fermt1
- doc_id: `medlineplus_genetics:gene-23071` | sections: 2
- automated checks: all pass
- first 300 characters: The FERMT1 gene provides instructions for making a protein called kindlin-1. This protein is found in epithelial cells, which are the cells that line the surfaces and cavities of the body. In the skin, kindlin-1 plays a critical role in specialized cells called keratinocytes, which are the major com
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 47. FGFR3 gene (fibroblast growth factor receptor 3)

- source: `medlineplus_genetics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/genetics/gene/fgfr3
- doc_id: `medlineplus_genetics:gene-21718` | sections: 2
- automated checks: all pass
- first 300 characters: The FGFR3 gene provides instructions for making a protein called fibroblast growth factor receptor 3. This protein is part of a family of four fibroblast growth factor receptors that share similar structures and functions. These proteins play a role in several important cellular processes, including
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 48. GNAQ gene (G protein subunit alpha q)

- source: `medlineplus_genetics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/genetics/gene/gnaq
- doc_id: `medlineplus_genetics:gene-23115` | sections: 2
- automated checks: all pass
- first 300 characters: The GNAQ gene provides instructions for making a protein called guanine nucleotide-binding protein G(q) subunit alpha (Gαq). The Gαq protein is part of a group of proteins called the trimeric G protein complex. This complex attaches (binds) to other proteins called G protein coupled receptors. When 
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 49. HADHA gene (hydroxyacyl-CoA dehydrogenase trifunctional multienzyme complex subunit alpha)

- source: `medlineplus_genetics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/genetics/gene/hadha
- doc_id: `medlineplus_genetics:gene-21838` | sections: 2
- automated checks: all pass
- first 300 characters: The HADHA gene provides instructions for making part of an enzyme complex called mitochondrial trifunctional protein. This enzyme complex functions in mitochondria, the energy-producing centers within cells. Mitochondrial trifunctional protein is made of eight parts (subunits). Four alpha subunits a
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 50. ISCU gene (iron-sulfur cluster assembly enzyme)

- source: `medlineplus_genetics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/genetics/gene/iscu
- doc_id: `medlineplus_genetics:gene-22915` | sections: 2
- automated checks: all pass
- first 300 characters: The ISCU gene provides instructions for making a protein called the iron-sulfur cluster assembly enzyme. As its name suggests, this enzyme is involved in the formation of clusters of iron and sulfur atoms (Fe-S clusters). Specifically, the enzyme acts as a platform, or scaffold, for the assembly of 
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 51. MYH6 gene (myosin heavy chain 6)

- source: `medlineplus_genetics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/genetics/gene/myh6
- doc_id: `medlineplus_genetics:gene-22671` | sections: 2
- automated checks: all pass
- first 300 characters: The MYH6 gene provides instructions for making a protein known as the cardiac alpha (α)-myosin heavy chain. This protein is found in heart (cardiac) muscle cells, where it forms part of a larger protein called type II myosin. Type II myosin helps generate the mechanical force that is needed for card
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 52. OFD1 gene (OFD1 centriole and centriolar satellite protein)

- source: `medlineplus_genetics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/genetics/gene/ofd1
- doc_id: `medlineplus_genetics:gene-21926` | sections: 2
- automated checks: all pass
- first 300 characters: The OFD1 gene provides instructions for making a protein whose function is not fully understood. It appears to play a critical role in the early development of many parts of the body, including the brain, face, limbs, and kidneys. The OFD1 protein is located at the base of cilia, which are finger-li
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 53. PDP1 gene (pyruvate dehydrogenase phosphatase catalytic subunit 1)

- source: `medlineplus_genetics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/genetics/gene/pdp1
- doc_id: `medlineplus_genetics:gene-22265` | sections: 2
- automated checks: all pass
- first 300 characters: The PDP1 gene provides instructions for making a protein called pyruvate dehydrogenase phosphatase 1, which is part of a large group of proteins called the pyruvate dehydrogenase complex. The pyruvate dehydrogenase phosphatase 1 protein turns on (activates) the complex by removing a phosphate group 
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 54. PHKB gene (phosphorylase kinase regulatory subunit beta)

- source: `medlineplus_genetics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/genetics/gene/phkb
- doc_id: `medlineplus_genetics:gene-22371` | sections: 2
- automated checks: all pass
- first 300 characters: The PHKB gene provides instructions for making one piece, the beta subunit, of the phosphorylase b kinase enzyme. This enzyme is made up of 16 subunits, four each of the alpha, beta, gamma, and delta subunits. (Each subunit is produced from a different gene.) The beta subunit helps regulate the acti
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 55. POLR3A gene (RNA polymerase III subunit A)

- source: `medlineplus_genetics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/genetics/gene/polr3a
- doc_id: `medlineplus_genetics:gene-22573` | sections: 2
- automated checks: all pass
- first 300 characters: The POLR3A gene provides instructions for making the largest piece (subunit) of an enzyme called RNA polymerase III. This enzyme is involved in the production (synthesis) of RNA, a chemical cousin of DNA. The RNA polymerase III enzyme attaches (binds) to DNA and synthesizes RNA molecules using the i
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 56. PRPH2 gene (peripherin 2)

- source: `medlineplus_genetics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/genetics/gene/prph2
- doc_id: `medlineplus_genetics:gene-21783` | sections: 2
- automated checks: all pass
- first 300 characters: The PRPH2 gene (also known as RDS) provides instructions for making a protein called peripherin 2. This protein plays an important role in normal vision. Peripherin 2 is found in the retina, the light-sensitive tissue that lines the back of the eye. This protein is essential for the normal function 
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 57. RIT1 gene (Ras like without CAAX 1)

- source: `medlineplus_genetics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/genetics/gene/rit1
- doc_id: `medlineplus_genetics:gene-23065` | sections: 2
- automated checks: all pass
- first 300 characters: The RIT1 gene provides instructions for making a protein that helps cells survive during periods of cellular stress, such as unusually high energy demands. As part of a signaling pathway known as the RAS/MAPK pathway, the RIT1 protein relays signals from outside the cell to the cell's nucleus. These
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 58. TCIRG1 gene (T cell immune regulator 1, ATPase H+ transporting V0 subunit a3)

- source: `medlineplus_genetics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/genetics/gene/tcirg1
- doc_id: `medlineplus_genetics:gene-22255` | sections: 2
- automated checks: all pass
- first 300 characters: The TCIRG1 gene provides instructions for making one part, the a3 subunit, of a large protein complex known as a vacuolar H+-ATPase (V-ATPase). V-ATPases are a group of similar complexes that act as pumps to move positively charged hydrogen atoms (protons) across membranes. This movement of protons 
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 59. Abscess

- source: `medlineplus_topics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/abscess.html
- doc_id: `medlineplus_topics:3063` | sections: 1
- automated checks: all pass
- first 300 characters: An abscess is a pocket of pus. You can get an abscess almost anywhere in your body. When an area of your body becomes infected, your body's immune system tries to fight the infection. White blood cells go to the infected area, collect within the damaged tissue, and cause inflammation. During this pr
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 60. Botulism

- source: `medlineplus_topics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/botulism.html
- doc_id: `medlineplus_topics:1557` | sections: 1
- automated checks: all pass
- first 300 characters: Botulism is a rare but serious illness. The cause is a toxin (poison) made by a bacterium called Clostridium botulinum. It occurs naturally in soil. There are several kinds of botulism. Foodborne botulism comes from eating foods contaminated with the toxin. Wound botulism happens when a wound infect
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 61. Childhood Brain Tumors

- source: `medlineplus_topics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/childhoodbraintumors.html
- doc_id: `medlineplus_topics:4177` | sections: 1
- automated checks: all pass
- first 300 characters: Brain tumors are abnormal growths inside the skull. They are among the most common types of childhood cancers. Some are benign tumors, which aren't cancer. They can still be serious. Malignant tumors are cancerous. Childhood brain and spinal cord tumors can cause headaches and other symptoms. Howeve
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 62. Cloning

- source: `medlineplus_topics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/cloning.html
- doc_id: `medlineplus_topics:1606` | sections: 1
- automated checks: all pass
- first 300 characters: Cloning describes the processes used to create an exact genetic replica of another cell, tissue or organism. The copied material, which has the same genetic makeup as the original, is referred to as a clone. The most famous clone was a Scottish sheep named Dolly. There are three different types of c
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 63. Elbow Injuries and Disorders

- source: `medlineplus_topics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/elbowinjuriesanddisorders.html
- doc_id: `medlineplus_topics:506` | sections: 1
- automated checks: all pass
- first 300 characters: Your elbow joint is made up of bone, cartilage, ligaments and fluid. Muscles and tendons help the elbow joint move. When any of these structures is hurt or diseased, you have elbow problems. Many things can make your elbow hurt. A common cause is tendinitis, an inflammation or injury to the tendons 
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 64. Hay Fever

- source: `medlineplus_topics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/hayfever.html
- doc_id: `medlineplus_topics:4746` | sections: 1
- automated checks: all pass
- first 300 characters: Each spring, summer, and fall, trees, weeds, and grasses release tiny pollen grains into the air. Some of the pollen ends up in your nose and throat. This can trigger a type of allergy called hay fever. Symptoms can include: - Sneezing, often with a runny or clogged nose - Coughing and postnasal dri
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 65. Helicobacter pylori Infections

- source: `medlineplus_topics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/helicobacterpyloriinfections.html
- doc_id: `medlineplus_topics:6078` | sections: 1
- automated checks: all pass
- first 300 characters: Helicobacter pylori (H. pylori) is a type of bacteria that causes infection in the stomach. It is the main cause of peptic ulcers, and it can also cause gastritis and stomach cancer. About 30 to 40% of people in the United States get an H. pylori infection. Most people get it as a child. H. pylori u
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 66. Hurricanes

- source: `medlineplus_topics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/hurricanes.html
- doc_id: `medlineplus_topics:4614` | sections: 1
- automated checks: all pass
- first 300 characters: A hurricane is a severe type of tropical storm. Hurricanes produce high winds, heavy rains and thunderstorms. Hurricanes can cause tremendous damage. Winds can exceed 155 miles per hour. Hurricanes and tropical storms can also spawn tornadoes and lead to flooding. The high winds and heavy rains can 
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 67. Mpox

- source: `medlineplus_topics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/mpox.html
- doc_id: `medlineplus_topics:3229` | sections: 7
- automated checks: all pass
- first 300 characters: Mpox, which used to be called monkeypox, is a disease caused by the monkeypox virus. This virus is in the same family of viruses as the smallpox virus. Mpox can be spread between animals and people, but it's mainly spread through close contact with someone who has it. It is found regularly in parts 
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 68. Mumps

- source: `medlineplus_topics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/mumps.html
- doc_id: `medlineplus_topics:334` | sections: 1
- automated checks: all pass
- first 300 characters: Mumps is an illness caused by the mumps virus. It starts with: - Fever - Headache - Muscle aches - Tiredness - Loss of appetite After that, the salivary glands under the ears or jaw become swollen and tender. The swelling can be on one or both sides of the face. Symptoms last 7 to 10 days. Serious c
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 69. Shingles

- source: `medlineplus_topics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/shingles.html
- doc_id: `medlineplus_topics:90` | sections: 8
- automated checks: all pass
- first 300 characters: Shingles (herpes zoster) is an infection that causes a painful rash. It is caused by the varicella-zoster virus (VZV). This is the same virus that causes chickenpox. After you have chickenpox, the virus stays in your body. It may not cause problems for many years. But as you get older, the virus may
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 70. Tremor

- source: `medlineplus_topics` | language: `en` | audience: `patient` | licence: `public-domain-us-gov` | reuse: `paraphrase_ok`
- URL: https://medlineplus.gov/tremor.html
- doc_id: `medlineplus_topics:1315` | sections: 7
- automated checks: all pass
- first 300 characters: A tremor is a neurological condition that includes shaking or trembling movements in one or more parts of your body. It most often affects the hands. But it can also affect the arms, legs, head, vocal cords, and torso (trunk). A tremor is involuntary, meaning that you cannot control it. It happens b
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 71. Grape Seed Extract

- source: `nccih` | language: `en` | audience: `patient` | licence: `us-gov-public-domain-nccih` | reuse: `paraphrase_ok`
- URL: https://www.nccih.nih.gov/health/grape-seed-extract
- doc_id: `nccih:health/grape-seed-extract` | sections: 10
- automated checks: FAILED: text_sanitised
- first 300 characters: Common Names: grape seed extract Latin Names: Vitis vinifera - Grape seed extract, which is made from the seeds of wine grapes, is promoted as a dietary supplement for various purposes, including reducing blood cholesterol and blood pressure, and as an ingredient in topical products for promoting wo
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 72. The Ginkgo Evaluation of Memory (GEM) Study

- source: `nccih` | language: `en` | audience: `patient` | licence: `us-gov-public-domain-nccih` | reuse: `paraphrase_ok`
- URL: https://www.nccih.nih.gov/health/the-ginkgo-evaluation-of-memory-gem-study
- doc_id: `nccih:health/the-ginkgo-evaluation-of-memory-gem-study` | sections: 1
- automated checks: all pass
- first 300 characters: In a study published in the Journal of the American Medical Association, 240 milligrams per day of the dietary supplement Ginkgo biloba was found to be ineffective in reducing the development of dementia and Alzheimer's disease in older people. Researchers led by Steven T. DeKosky, M.D., conducted t
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 73. Childhood Ovarian Cancer (PDQ®)–Patient Version

- source: `nci_pdq` | language: `en` | audience: `patient` | licence: `us-gov-free-of-copyright-nci` | reuse: `paraphrase_ok`
- URL: https://www.cancer.gov/types/ovarian/patient/child-ovarian-treatment-pdq
- doc_id: `nci_pdq:ovarian/patient/child-ovarian-treatment-pdq` | sections: 35
- automated checks: all pass
- first 300 characters: Childhood ovarian tumors form in the tissues of the ovaries. Most ovarian tumors in children are not cancer. Ovarian cancer in children is very rare but occurs most often in females aged 15 to 19 years. The ovaries are a pair of organs in the female reproductive system. They are in the pelvis, one o
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 74. Aniridia Foundation International (AFI)

- source: `nei` | language: `en` | audience: `patient` | licence: `us-gov-public-domain-nei` | reuse: `paraphrase_ok`
- URL: https://www.nei.nih.gov/eye-health-information/eye-conditions-and-diseases/eye-health-organizations-database/aniridia-foundation-international-afi
- doc_id: `nei:eye-health-information/eye-conditions-and-diseases/eye-health-organizations-database/aniridia-foundation-international-afi` | sections: 1
- automated checks: all pass
- first 300 characters: The Aniridia Foundation International is a 501(c)3 non-profit organization dedicated to assisting those with low vision or blindness due to aniridia, a genetic syndrome. Support services, educational and social programs, and medical / research conferences featuring top physicians and researchers wit
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 75. Macular Degeneration Foundation, Inc.

- source: `nei` | language: `en` | audience: `patient` | licence: `us-gov-public-domain-nei` | reuse: `paraphrase_ok`
- URL: https://www.nei.nih.gov/eye-health-information/eye-conditions-and-diseases/eye-health-organizations-database/macular-degeneration-foundation-inc
- doc_id: `nei:eye-health-information/eye-conditions-and-diseases/eye-health-organizations-database/macular-degeneration-foundation-inc` | sections: 1
- automated checks: all pass
- first 300 characters: The Macular Degeneration Foundation provides a website (www.eyesight.org) as an informational tool for patients, universities, insurance companies etc. They also provide a toll-free number that patients may call for mail-out packets or for quick questions. The Foundation has a quarterly newsletter (
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 76. Bleeding Disorders Diagnosis

- source: `nhlbi` | language: `en` | audience: `patient` | licence: `us-gov-public-domain-nhlbi` | reuse: `quote_only`
- URL: https://www.nhlbi.nih.gov/health/bleeding-disorders/diagnosis
- doc_id: `nhlbi:health/bleeding-disorders/diagnosis` | sections: 8
- automated checks: FAILED: text_sanitised
- first 300 characters: Bleeding Disorders Your healthcare provider may diagnose your bleeding disorder, and determine whether it is inherited or acquired, based on your symptoms, risk factors, medical and family history, a physical exam, and diagnostic tests. Typically, providers screen for bleeding disorders only if you 
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 77. Heart-Healthy Living Quit Smoking

- source: `nhlbi` | language: `en` | audience: `patient` | licence: `us-gov-public-domain-nhlbi` | reuse: `quote_only`
- URL: https://www.nhlbi.nih.gov/health/heart-healthy-living/quit-smoking
- doc_id: `nhlbi:health/heart-healthy-living/quit-smoking` | sections: 1
- automated checks: all pass
- first 300 characters: Heart-Healthy Living If you smoke, quit. Smoking can raise your risk of heart disease and heart attack and worsen other heart disease risk factors. Talk with your doctor about programs and products that can help you quit smoking. Also, try to avoid secondhand smoke. Smoking and Your Heart has more i
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 78. High Blood Pressure Treatment

- source: `nhlbi` | language: `en` | audience: `patient` | licence: `us-gov-public-domain-nhlbi` | reuse: `quote_only`
- URL: https://www.nhlbi.nih.gov/health/high-blood-pressure/treatment
- doc_id: `nhlbi:health/high-blood-pressure/treatment` | sections: 4
- automated checks: all pass
- first 300 characters: High Blood Pressure For most people with high blood pressure, a healthcare provider will work with you to develop a treatment plan that may include heart-healthy lifestyle changes alone or with medicines. Your provider can help you manage your blood pressure and prevent complications. They may use a
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 79. Marfan Syndrome Diagnosis

- source: `nhlbi` | language: `en` | audience: `patient` | licence: `us-gov-public-domain-nhlbi` | reuse: `quote_only`
- URL: https://www.nhlbi.nih.gov/health/marfan-syndrome/diagnosis
- doc_id: `nhlbi:health/marfan-syndrome/diagnosis` | sections: 4
- automated checks: all pass
- first 300 characters: Marfan Syndrome You will be diagnosed with Marfan syndrome based on your medical and family history, a physical exam, and test results. If you are diagnosed with Marfan syndrome, your parents, siblings, and children should be screened for the disorder, even if they do not have symptoms. To screen fo
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 80. Sleep Apnea Symptoms

- source: `nhlbi` | language: `en` | audience: `patient` | licence: `us-gov-public-domain-nhlbi` | reuse: `quote_only`
- URL: https://www.nhlbi.nih.gov/health/sleep-apnea/symptoms
- doc_id: `nhlbi:health/sleep-apnea/symptoms` | sections: 1
- automated checks: FAILED: text_sanitised
- first 300 characters: Sleep Apnea While asleep, you may have these symptoms of sleep apnea: - Breathing that starts and stops - Frequent loud snoring (more common in men) - Gasping for air You may not know you have these symptoms until someone tells you. Or you may notice the following symptoms yourself: - Daytime sleepi
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 81. Health Lesson: Learning About Skin

- source: `niams` | language: `en` | audience: `patient` | licence: `us-gov-public-domain-niams` | reuse: `paraphrase_ok`
- URL: https://www.niams.nih.gov/health-topics/educational-resources/health-lesson-learning-about-skin
- doc_id: `niams:health-topics/educational-resources/health-lesson-learning-about-skin` | sections: 29
- automated checks: FAILED: text_sanitised
- first 300 characters: Information on this page is mapped to national science and health education standards and is for students in grades 4 through 6 who are learning about the human body. Teachers may also use these resources to inform their lesson plans. - For Students : Find all classroom materials and activities abou
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 82. Adrenal Gland Disorder Research Activities and Advances

- source: `nichd` | language: `en` | audience: `patient` | licence: `us-gov-public-domain-nichd` | reuse: `paraphrase_ok`
- URL: https://www.nichd.nih.gov/health/topics/adrenalgland/researchinfo/activities
- doc_id: `nichd:health/topics/adrenalgland/researchinfo/activities` | sections: 2
- automated checks: all pass
- first 300 characters: Through its intramural and extramural organizational units, NICHD supports and conducts a variety of research on adrenal gland disorders. Through its intramural and extramural organizational units, NICHD supports and conducts a broad range of research on adrenal gland disorders. Much of this researc
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 83. Breastfeeding and Breast Milk

- source: `nichd` | language: `en` | audience: `patient` | licence: `us-gov-public-domain-nichd` | reuse: `paraphrase_ok`
- URL: https://www.nichd.nih.gov/health/topics/breastfeeding
- doc_id: `nichd:health/topics/breastfeeding` | sections: 14
- automated checks: all pass
- first 300 characters: Breastfeeding provides an infant with essential calories, vitamins, minerals, and other nutrients for optimal growth, health, and development. Breastfeeding is beneficial to both a mother and her infant and also offers an important opportunity for the pair to bond. NICHD supports many areas of breas
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 84. What are some factors that make a pregnancy high risk?

- source: `nichd` | language: `en` | audience: `patient` | licence: `us-gov-public-domain-nichd` | reuse: `paraphrase_ok`
- URL: https://www.nichd.nih.gov/health/topics/high-risk/conditioninfo/factors
- doc_id: `nichd:health/topics/high-risk/conditioninfo/factors` | sections: 2
- automated checks: all pass
- first 300 characters: Several factors can make a pregnancy high risk, including existing health conditions, the mother’s age, lifestyle, and health issues that happen before or during pregnancy. This page provides some possible factors that could create a high-risk pregnancy situation. This list is not meant to be all-in
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 85. NICHD High-Risk Pregnancy Research Information

- source: `nichd` | language: `en` | audience: `patient` | licence: `us-gov-public-domain-nichd` | reuse: `paraphrase_ok`
- URL: https://www.nichd.nih.gov/health/topics/high-risk/researchinfo
- doc_id: `nichd:health/topics/high-risk/researchinfo` | sections: 3
- automated checks: all pass
- first 300 characters: A core purpose of NICHD’s research is to help ensure that women have no harmful effects from reproductive processes, including pregnancy and childbirth. High-risk pregnancy encompasses a range of risks that can affect the pregnancy and the fetus, as well as the mother’s and baby’s long-term health. 
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 86. Assisted Reproductive Technology (ART)

- source: `nichd` | language: `en` | audience: `patient` | licence: `us-gov-public-domain-nichd` | reuse: `paraphrase_ok`
- URL: https://www.nichd.nih.gov/health/topics/infertility/conditioninfo/treatments/art
- doc_id: `nichd:health/topics/infertility/conditioninfo/treatments/art` | sections: 10
- automated checks: all pass
- first 300 characters: ART refers to treatments and procedures that aim to achieve pregnancy. These complex procedures may be an option for people who have already gone through various infertility treatment options but who still have not achieved pregnancy. Those interested in ART should discuss the options with their hea
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 87. Find a Study on Menstruation and Menstrual Problems

- source: `nichd` | language: `en` | audience: `patient` | licence: `us-gov-public-domain-nichd` | reuse: `paraphrase_ok`
- URL: https://www.nichd.nih.gov/health/topics/menstruation/clinicaltrials
- doc_id: `nichd:health/topics/menstruation/clinicaltrials` | sections: 1
- automated checks: all pass
- first 300 characters: Select one of the following links to get ClinicalTrials.gov search results for studies on menstruation and menstrual problems: - All NICHD clinical trials on menstruation and menstrual problems - All NICHD clinical trials on menstrual irregularities - All ClinicalTrials.gov trials on menstruation an
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 88. How is muscular dystrophy (MD) diagnosed?

- source: `nichd` | language: `en` | audience: `patient` | licence: `us-gov-public-domain-nichd` | reuse: `paraphrase_ok`
- URL: https://www.nichd.nih.gov/health/topics/musculardys/conditioninfo/diagnosed
- doc_id: `nichd:health/topics/musculardys/conditioninfo/diagnosed` | sections: 2
- automated checks: all pass
- first 300 characters: The first step in diagnosing MD is a visit with a healthcare provider for a physical exam. He or she will ask a series of questions about the person’s family history, including any family members with MD, and medical history, such as muscle problems the person may be experiencing. Different tests ca
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 89. About Pelvic Floor Disorders (PFDs)

- source: `nichd` | language: `en` | audience: `patient` | licence: `us-gov-public-domain-nichd` | reuse: `paraphrase_ok`
- URL: https://www.nichd.nih.gov/health/topics/pelvicfloor/conditioninfo
- doc_id: `nichd:health/topics/pelvicfloor/conditioninfo` | sections: 3
- automated checks: all pass
- first 300 characters: The “pelvic floor” is the group of muscles that form a sling or hammock across the floor of the pelvis. Together with surrounding tissues, these muscles hold the pelvic organs in place so they can function correctly. The pelvic organs include the bladder, urethra, intestines, and rectum. A woman’s p
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 90. NICHD Pharmacology Research Information

- source: `nichd` | language: `en` | audience: `patient` | licence: `us-gov-public-domain-nichd` | reuse: `paraphrase_ok`
- URL: https://www.nichd.nih.gov/health/topics/pharma/researchinfo
- doc_id: `nichd:health/topics/pharma/researchinfo` | sections: 3
- automated checks: all pass
- first 300 characters: Research in pharmacology, particularly for pregnant women and children, has advanced significantly in recent years, due in large part to the commitment and support of NICHD. NICHD created the Obstetric & Pediatric Pharmacology Branch to support pharmacologic research for pregnant women and children.
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 91. Pregnancy Loss (Before 20 Weeks of Pregnancy)

- source: `nichd` | language: `en` | audience: `patient` | licence: `us-gov-public-domain-nichd` | reuse: `paraphrase_ok`
- URL: https://www.nichd.nih.gov/health/topics/pregnancyloss
- doc_id: `nichd:health/topics/pregnancyloss` | sections: 10
- automated checks: FAILED: text_sanitised
- first 300 characters: Pregnancy loss occurs when a pregnancy ends unexpectedly before the 20th week. It is sometimes called early pregnancy loss, mid-trimester pregnancy loss, miscarriage, spontaneous abortion, or fetal demise. We use the term "pregnancy loss" throughout this information. NICHD supports and conducts rese
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 92. What are the symptoms of SCI?

- source: `nichd` | language: `en` | audience: `patient` | licence: `us-gov-public-domain-nichd` | reuse: `paraphrase_ok`
- URL: https://www.nichd.nih.gov/health/topics/spinalinjury/conditioninfo/symptoms
- doc_id: `nichd:health/topics/spinalinjury/conditioninfo/symptoms` | sections: 2
- automated checks: all pass
- first 300 characters: According to the American Association of Neurological Surgeons, there are many different symptoms or signs of SCI. Some of the more common signs of SCI include1: - Extreme pain or pressure in the neck, head, or back - Tingling or loss of sensation in the hand, fingers, feet, or toes - Partial or com
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 93. Low Blood Glucose (Hypoglycemia)

- source: `niddk` | language: `en` | audience: `patient` | licence: `us-gov-copyright-free-niddk` | reuse: `paraphrase_ok`
- URL: https://www.niddk.nih.gov/health-information/diabetes/overview/preventing-problems/low-blood-glucose-hypoglycemia
- doc_id: `niddk:diabetes/overview/preventing-problems/low-blood-glucose-hypoglycemia` | sections: 11
- automated checks: all pass
- first 300 characters: Low blood glucose, also called low blood sugar or hypoglycemia, occurs when the level of glucose in your blood drops below what is healthy for you. For many people with diabetes, this means a blood glucose reading lower than 70 milligrams per deciliter (mg/dL).1 Your number might be different, so ch
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 94. Diabetes, Sexual, & Bladder Problems

- source: `niddk` | language: `en` | audience: `patient` | licence: `us-gov-copyright-free-niddk` | reuse: `paraphrase_ok`
- URL: https://www.niddk.nih.gov/health-information/diabetes/overview/preventing-problems/sexual-bladder-problems
- doc_id: `niddk:diabetes/overview/preventing-problems/sexual-bladder-problems` | sections: 21
- automated checks: all pass
- first 300 characters: - Can sexual and bladder problems be symptoms of diabetes? - When should I see a doctor about my sexual or bladder problems? - What makes me more likely to develop sexual or bladder problems? - What sexual problems can men with diabetes have? - What sexual problems can women with diabetes have? - Wh
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 95. Acid Reflux (GER & GERD) in Adults

- source: `niddk` | language: `en` | audience: `patient` | licence: `us-gov-copyright-free-niddk` | reuse: `paraphrase_ok`
- URL: https://www.niddk.nih.gov/health-information/digestive-diseases/acid-reflux-ger-gerd-adults
- doc_id: `niddk:digestive-diseases/acid-reflux-ger-gerd-adults` | sections: 7
- automated checks: all pass
- first 300 characters: Gastroesophageal reflux (GER) happens when your stomach contents come back up into your esophagus. Gastroesophageal reflux disease (GERD) is a more severe and long-lasting condition in which GER causes repeated symptoms or leads to complications over time. Gastroesophageal reflux (GER) and gastroeso
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 96. Dieting & Gallstones

- source: `niddk` | language: `en` | audience: `patient` | licence: `us-gov-copyright-free-niddk` | reuse: `paraphrase_ok`
- URL: https://www.niddk.nih.gov/health-information/digestive-diseases/gallstones/dieting
- doc_id: `niddk:digestive-diseases/gallstones/dieting` | sections: 5
- automated checks: all pass
- first 300 characters: - How does weight affect gallstones? - How does my fast weight loss affect gallstones? - Is weight cycling a problem? - How can I safely lose weight to lower my chances of getting gallstones? Being overweight or having obesity may make you more likely to develop gallstones, especially if you are a w
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 97. Treatment of Indigestion

- source: `niddk` | language: `en` | audience: `patient` | licence: `us-gov-copyright-free-niddk` | reuse: `paraphrase_ok`
- URL: https://www.niddk.nih.gov/health-information/digestive-diseases/indigestion-dyspepsia/treatment
- doc_id: `niddk:digestive-diseases/indigestion-dyspepsia/treatment` | sections: 5
- automated checks: all pass
- first 300 characters: How doctors treat indigestion depends on the cause. Your doctor may recommend over-the-counter or prescription medicines, changing what you eat and drink, or mental health therapies. You can buy many medicines to treat indigestion without a prescription, such as H2 blockers or proton pump inhibitors
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 98. Definition & Facts for Irritable Bowel Syndrome in Children

- source: `niddk` | language: `en` | audience: `patient` | licence: `us-gov-copyright-free-niddk` | reuse: `paraphrase_ok`
- URL: https://www.niddk.nih.gov/health-information/digestive-diseases/irritable-bowel-syndrome-children/definition-facts
- doc_id: `niddk:digestive-diseases/irritable-bowel-syndrome-children/definition-facts` | sections: 10
- automated checks: all pass
- first 300 characters: - What is IBS? - Does IBS have another name? - Are there different types of IBS in children? - How common is IBS in children? - Which children are more likely to develop IBS? Irritable bowel syndrome (IBS) is a group of symptoms that occur together, including repeated pain in the abdomen and changes
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 99. Hyperthyroidism (Overactive Thyroid)

- source: `niddk` | language: `en` | audience: `patient` | licence: `us-gov-copyright-free-niddk` | reuse: `paraphrase_ok`
- URL: https://www.niddk.nih.gov/health-information/endocrine-diseases/hyperthyroidism
- doc_id: `niddk:endocrine-diseases/hyperthyroidism` | sections: 16
- automated checks: all pass
- first 300 characters: Hyperthyroidism, also called overactive thyroid, is when the thyroid gland makes more thyroid hormones than your body needs. The thyroid is a small, butterfly-shaped gland in the front of your neck. Thyroid hormones control the way the body uses energy, so they affect nearly every organ in your body
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 100. Eating, Diet, & Nutrition for Hemochromatosis

- source: `niddk` | language: `en` | audience: `patient` | licence: `us-gov-copyright-free-niddk` | reuse: `paraphrase_ok`
- URL: https://www.niddk.nih.gov/health-information/liver-disease/hemochromatosis/eating-diet-nutrition
- doc_id: `niddk:liver-disease/hemochromatosis/eating-diet-nutrition` | sections: 2
- automated checks: all pass
- first 300 characters: If you have hemochromatosis, you should eat a healthy, well-balanced diet. Talk with your doctor, a dietitian, or a nutritionist about healthy eating. Your doctor may recommend avoiding - raw or undercooked shellfish, which can cause a serious infection in people with liver disease - supplements tha
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 101. Motivational Interviewing: Do's and Don'ts

- source: `niddk` | language: `en` | audience: `professional` | licence: `us-gov-copyright-free-niddk` | reuse: `paraphrase_ok`
- URL: https://www.niddk.nih.gov/health-information/professionals/diabetes-discoveries-practice/motivational-interviewing-dos-donts
- doc_id: `niddk:professionals/diabetes-discoveries-practice/motivational-interviewing-dos-donts` | sections: 2
- automated checks: all pass
- first 300 characters: Uncovering a patient’s emotions and ambivalence about treatment may lead to a more energized patient with better health. Motivational interviewing (MI) is a set of communication techniques that can spark behavior change in people with chronic conditions such as diabetes. This style of communication 
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 102. Eating, Diet, & Nutrition for Bladder Infection in Children

- source: `niddk` | language: `en` | audience: `patient` | licence: `us-gov-copyright-free-niddk` | reuse: `paraphrase_ok`
- URL: https://www.niddk.nih.gov/health-information/urologic-diseases/urinary-tract-infections-in-children/eating-diet-nutrition
- doc_id: `niddk:urologic-diseases/urinary-tract-infections-in-children/eating-diet-nutrition` | sections: 2
- automated checks: all pass
- first 300 characters: Researchers don’t think that diet can help prevent or treat most bladder infections in children. However, eating high-fiber foods to prevent constipation may help prevent some bladder infections in children. Cranberry products—including cranberry juice, extract, or pills—don’t treat existing bladder
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 103. Publications about Schizophrenia

- source: `nimh` | language: `en` | audience: `patient` | licence: `us-gov-public-domain-nimh` | reuse: `paraphrase_ok`
- URL: https://www.nimh.nih.gov/health/publications/schizophrenia-listing
- doc_id: `nimh:health/publications/schizophrenia-listing` | sections: 1
- automated checks: all pass
- first 300 characters: Schizophrenia This brochure provides information about schizophrenia including symptoms, causes, treatment options, and how to find help for yourself or a loved one. En español Understanding Psychosis This fact sheet presents information on psychosis including causes, signs and symptoms, treatment, 
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 104. Tap Water Detox (Tap Water Detox 6018) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=ae0bca6a-118e-40a2-9108-14fc41552444
- doc_id: `openfda_labels:ae0bca6a-118e-40a2-9108-14fc41552444` | sections: 7
- automated checks: all pass
- first 300 characters: For the temporary relief of mild abdominal pain, nausea or vomiting, shortness of breath, minor rash or itchy skin, or occasional headache due to sensitivity to or exposure to common tap water additives or contaminants.\* \*Claims based on traditional homeopathic practice, not accepted medical evide
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 105. 7-Oxo-Dehydroepiandrosterone 3-Acetate, Aacg-A, Aacg-B, Adenosinum Triphosphoricum Dinatrum, Asclepias Vincetoxicum, Calcarea Carbonica, Cerebrum Suis, Echinacea (Angustifolia), Gambogia, Gelsemium Sempervirens, Graphites, Hepar Suis, Hypothalamus (Suis), Insulinum (Suis), Kidney (Suis), Methylcobalamin, Nux Vomica, Pancreas Suis, Phytolacca Decandra, Proteus (Vulgaris), Sarcolacticum Acidum, Stomach (Suis) (HA2CG Evolution) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=9bce2d3a-c0b3-4f5a-8a26-ead87abb61f5
- doc_id: `openfda_labels:9bce2d3a-c0b3-4f5a-8a26-ead87abb61f5` | sections: 6
- automated checks: all pass
- first 300 characters: For the temporary relief of symptoms including: • symptoms related to increased appetite • regulation of fat metabolism • headache • fatigue These statements are based upon homeopathic principles. They have not been reviewed by the Food and Drug Administration. 7-Oxo-Dehydroepiandrosterone 3-Acetate
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 106. Trees 1 (Trees 1 1016) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=7c5824f2-6c8f-418d-97b0-69c62db18ab7
- doc_id: `openfda_labels:7c5824f2-6c8f-418d-97b0-69c62db18ab7` | sections: 7
- automated checks: all pass
- first 300 characters: For the temporary relief of runny nose, sneezing, itching of the nose or throat, and itchy, watery eyes due to sensitivity to broadleaf and needle-bearing trees.\* \*Claims based on traditional homeopathic practice, not accepted medical evidence. Not FDA evaluated. ACTIVE INGREDIENTS Adrenal 6X ACTH
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 107. Angelica Archangelica, Geranium Maculatum, Hydrastis Canadensis, Sinapis Nigra, Symphytum Officinale, Ratanhia, Aceticum Acidum, Carbolicum Acidum, Ornithogalum Umbellatum, Abies Canadensis, Anacardium Orientale, Bismuthum Subnitricum, Condurango, Graphites, Iris Versicolor, Kali Bichromicum, Lycopodium Clavatum, Mezereum, Euphorbium Officinarum, Nux Vomica (Hpyl Plus) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=c90278bf-b08a-4c79-86c0-dafd3b7756c6
- doc_id: `openfda_labels:c90278bf-b08a-4c79-86c0-dafd3b7756c6` | sections: 6
- automated checks: all pass
- first 300 characters: For the temporary relief of symptoms related to ulceration such as severe stomach pain, aching pain in stomach, diarrhea, difficulty swallowing, fatigue, and foul breath.\*\* \*\*These statements are based upon homeopathic principles. They have not been reviewed by the Food and Drug Administration. 
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 108. Triticum Aestivum, Berberis Vulgaris, Lappa Major, Rhamnus Purshiana, Senns (Cassia Angustifolia), Phytolacca Decandra, Glycyrrhiza Glabra, Stillingia Sylvatica, Trifolium Pratense, Xanthoxylum Fraxineum, Acetonum Acetone, Sodium Tripolyphosphate, Propylene Glycol, Benzinum, Ammonium Muriaticum, Sodium Lauryl Sulfate, Terebinthina, Belladonna, Lycopodium Clavatum, Nitricum Acidum, Nux Vomica, Phosphoricum Acidum, Belladonna, Lycopodium Clavatum, Nitricum Acidum, Nux Vomica, Phosphoricum Acidum. (Envirotox) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=2b5cfdba-cf4d-4eb0-8c60-20eac6922663
- doc_id: `openfda_labels:2b5cfdba-cf4d-4eb0-8c60-20eac6922663` | sections: 6
- automated checks: all pass
- first 300 characters: For temporary relief of head congestion & general exhaustion as a consequence of exposure to smog, dust, or industrial agents. INDICATIONS: For temporary relief of head congestion & general exhaustion as a consequence of exposure to smog, dust, or industrial agents. ACTIVE INGREDIENTS: Triticum Aest
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 109. Bellis Perennis, Calendula Officinalis, Hamamelis Virginiana, Millefollium Mt, Chamomilla, Ferrum Phosphoricum, Ledum Palustre, Magnesia Phosphorica, Apis Mellifica, Arnica Montana, Belladonna, Symphytum Officinale, Hypericum Perforatum. (Arnica Well) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=52647581-e65c-4f43-bb61-600174bc8e7e
- doc_id: `openfda_labels:52647581-e65c-4f43-bb61-600174bc8e7e` | sections: 6
- automated checks: all pass
- first 300 characters: Temporarily relieves pain and swelling from contusions, sprains, and hematomas as well as muscle and joint pains. Pain & Inflammation ACTIVE INGREDIENTS (HPUS\*): Bellis Perennis MT, Calendula Officinalis MT, Hamamelis Virginiana MT, Millefollium MT, Chamomilla 1X, Ferrum Phosphoricum 2X, Ledum Palu
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 110. Achillea Millefolium, Arnica Montana, Hypericum Perforatum, Horse Chestnut, And Viscum Album Whole (D82) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=2c24bb97-11be-450a-9cf9-5aadca1e8be1
- doc_id: `openfda_labels:2c24bb97-11be-450a-9cf9-5aadca1e8be1` | sections: 7
- automated checks: all pass
- first 300 characters: Stress, headache, sweating, rapid pulse, shortness of breath, dizziness, vision disturbances. INDICATIONS Stress, headache, sweating, rapid pulse, shortness of breath, dizziness, vision disturbances. INGREDIENTS Millefolium 3x, Arnica montana 6x, Hypericum perforatum 3x, Aesculus hippocastanum 2x, V
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 111. Aconitum Napellus, Alfalfa, Arabica Coffee Bean, Medicago Sativa Leaf, Bryonia Root, Calcium Cation, Spongia Officinalis Skeleton, Roasted, Tin (Cough and Bronchial Nighttime) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=31445469-8f7f-4729-8128-fc53d5e5ab06
- doc_id: `openfda_labels:31445469-8f7f-4729-8128-fc53d5e5ab06` | sections: 10
- automated checks: all pass
- first 300 characters: Temporarily relieves coughs due to minor throat and bronchial irritation as may occur with a cold. Helps loosen phlegm (mucus) and thin bronchial secretions to drain bronchial tubes. Soothes the throat. Temporarily relieves coughs due to minor throat and bronchial irritation as may occur with a cold
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 112. Aconitum Napellus, Bryonia Alba, Eupatorium Perfoliatum, Ferrum Phosphoricum, Gelsemium Sempervirens, Kali Bichromicum, Kali Lodatum, Zincum Gluconicum. (Cold) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=12c71753-bed4-4f0c-970e-8564b2dd2e2e
- doc_id: `openfda_labels:12c71753-bed4-4f0c-970e-8564b2dd2e2e` | sections: 6
- automated checks: all pass
- first 300 characters: Temporarily relieves symptoms caused by the common cold.\*\* \*\*This statement has not been evaluated by the FDA. It is based on documented Homeopathic Materia Medica. Temporarily relieves symptoms caused by the common cold. ACTIVE INGREDIENTS (HPUS\*): Equal amounts of: Aconitum Napellus 4X, Bryon
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 113. Anti-Scar Drops (Anti-Scar Drops 2084) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=ad0e9159-ed68-48aa-a7d1-7ff5c32ec304
- doc_id: `openfda_labels:ad0e9159-ed68-48aa-a7d1-7ff5c32ec304` | sections: 7
- automated checks: all pass
- first 300 characters: For the temporary relief of painful, sensitive, or itchy skin resulting from injury.\* \*Claims based on traditional homeopathic practice, not accepted medical evidence. Not FDA evaluated. ACTIVE INGREDIENTS Thuja occidentalis 3X, 6X, 12X, 24X, 30X Aconitum napellus 6X Alumen 6X Silicea 6X Calcarea 
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 114. Aconitum Napellus, Argentum Nitricum, Arnica Montana, Arsenicum Album, Astragalus Membranaceus, Baptisia Tinctoria, Bryonia (Alba), Calendula Officinalis, Cortisone Aceticum, Echinacea (Angustifolia), Eupatorium Perfoliatum, Euphorbium Officinalis, Gelsemium Sempervirens, Hepar Sulphuris Calcareum, Influenzinum, Lachesis Mutus, Mercurius Corrosivus, Phosphorus, Phytolacca Decandra, Pulsatilla (Pratensis), Pyrogenium, Rhus Tox, Sanguinaria Canadensis, Spleen (Suis), Sulphur, Thuja Occidentalis, Thymus, (Immune Support) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=8b5a4609-184d-4a43-823a-91024d9dc0c1
- doc_id: `openfda_labels:8b5a4609-184d-4a43-823a-91024d9dc0c1` | sections: 6
- automated checks: all pass
- first 300 characters: • For the temporary relief of symptoms including: • cough • fever • headache • fatigue • coldness • muscle pain • sore throat • ear congestion • nose congestion • throat congestion. These statements are based upon homeopathic principles. They have not been reviewed by the Food and Drug Administratio
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 115. Aconitum Napellus, Allium Cepa, Eupatorium Perfoliatum, Ferrum Phosphoricum, Gelsemium Sempervirens, Kali Bichromicum, Mercurius Solubilis, Nux Vomica, Pulsatilla (Vulgaris) (Cold HP) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=d13b3de8-b1bc-41bd-a964-c3d8ba9f29fd
- doc_id: `openfda_labels:d13b3de8-b1bc-41bd-a964-c3d8ba9f29fd` | sections: 6
- automated checks: all pass
- first 300 characters: May temporarily relieve symptoms of nasal congestion, runny nose, sneezing, irritated throat, fever/chills, and/or discharges.\*\* \*\*Claims based on traditional homeopathic practice, not accepted medical evidence. Not FDA evaluated. May temporarily relieve symptoms of nasal congestion, runny nose,
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 116. Leptandra Combination (Leptandra Combination 9230) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=2ce3a622-3d59-4a95-9dc2-22cd55b994a6
- doc_id: `openfda_labels:2ce3a622-3d59-4a95-9dc2-22cd55b994a6` | sections: 7
- automated checks: all pass
- first 300 characters: For the temporary relief of diarrhea, stomach or abdominal cramping, flatulence, nausea, or vomiting.\* \*Claims based on traditional homeopathic practice, not accepted medical evidence. Not FDA evaluated. ACTIVE INGREDIENTS Leptandra virginica 2X Quassia amara 3X Veratrum album 4X Arsenicum album 6
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 117. Helianthus Annuus (Sunflower) Seed 0Il ,Tocopherol,Adansonia Digitata Seed 0Il,Moringa Oleifera Seed 0Il,Theobroma Cacao (Cocoa) Seed Butter,Echium Plantagineum Seed Oil,Sesamum Indicum (Sesame) Seed 0Il (Body Oil for Stretch Marks) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=496af9a1-7249-622f-e063-6394a90aa284
- doc_id: `openfda_labels:496af9a1-7249-622f-e063-6394a90aa284` | sections: 7
- automated checks: all pass
- first 300 characters: Suitable for all types of skin damage due to stretching of the skin.Massage liberally into skin twice dally. Reapply as needed. Moisturise, Wrinkle Active Ingredients Helianthus Annuus (Sunflower) Seed 0il 50% Tocopherol 2% Adansonia Digitata Seed 0il 2% Moringa Oleifera Seed 0il 2% Theobroma cacao 
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 118. Adenosine Triphosphate, Ammonium Carbonicum, Camphora, Crotalus Cascavella, Fucus Vesiculosus, Iodium, Kali Phosphoricum, Levothyroxine, Triiodothyronine (R06 Thyroid) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=b57e5e22-cc23-1a29-e053-2a95a90aebf0
- doc_id: `openfda_labels:b57e5e22-cc23-1a29-e053-2a95a90aebf0` | sections: 8
- automated checks: all pass
- first 300 characters: For temporary relief of minor: fatigue\* dry skin\* hair loss\* sluggishness\* weight gain\* cold extremities\* constipation\* For temporary relief of minor: fatigue\* dry skin\* hair loss\* sluggishness\* weight gain\* cold extremities\* constipation\* Active Ingredients Adenosine Triphosphate Ammo
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 119. Abrotanum (Artemisia Abrotanum), Aethusa Cynapium, Baptisia Tinctoria, Cicuta Virosa, Cuprum Metallicum, Mezereum, Bufo Rana, Lac Materna Humanum, Saccharum Officinale, Serotonin (Hydrochloride), Alumina, Calcarea Phosphorica, Candida Albicans, Carcinosin, Lac Caninum, Mercurius Solubilis, Natrum Muriaticum, Propionic Acid, Sulphur, Thuja Occidentalis, Formalinum, Morbillinum (Gut Brain Spectrum) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=adfee6ce-05b0-4955-bf5f-9612b8db4c78
- doc_id: `openfda_labels:adfee6ce-05b0-4955-bf5f-9612b8db4c78` | sections: 6
- automated checks: all pass
- first 300 characters: May temporarily relieve symptoms of dullness with gastro-intestinal discomfort, feeling unconnected to others, and minor symptoms following vaccination.\*\* \*\*Claims based on traditional homeopathic practice, not accepted medical evidence. Not FDA evaluated. May temporarily relieve symptoms of dul
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 120. Aldesleukin - Arsenic Trioxide - Atropa Belladonna - Canakinumab - Echinacea Angustifolia - Graphite - Melatonin - Plantago Major - Solanum Dulcamara Flower - Sulfur - (Guna-Dermo) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=8bf717eb-fe46-4066-b124-eb715ffc1542
- doc_id: `openfda_labels:8bf717eb-fe46-4066-b124-eb715ffc1542` | sections: 7
- automated checks: all pass
- first 300 characters: Take 15 minutes before meals USES Temporary relief of symptoms of general skin irritation and rashes such as: Itching Dryness Hypersensitivity ACTIVE INGREDIENTS/PURPOSE ARSENICUM ALBUM 6C SKIN BLISTERS BELLADONNA 6C SWELLING DULCAMARA 6C MUSCLE SORENESS ECHINACEA ANGUSTIFOLIA 6C ANTI-INFECTION GRAP
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 121. Nitrogen Combination (Nitrogen Combination 9310) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=72a7c0f3-0a57-4aa8-8fe8-a3267b9acd53
- doc_id: `openfda_labels:72a7c0f3-0a57-4aa8-8fe8-a3267b9acd53` | sections: 7
- automated checks: all pass
- first 300 characters: For the temporary relief of abdominal pain, nausea or vomiting, diarrhea, or skin, eye, or upper respiratory irritation.\* \*Claims based on traditional homeopathic practice, not accepted medical evidence. Not FDA evaluated. ACTIVE INGREDIENTS Cimicifuga racemosa 3X Gelsemium sempervirens 3X Natrum 
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 122. Amlodipine Besylate And Olmesartran Medoxomil (Amlodipine and Olmesartan Medoxomil) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=cb2df7f7-fee8-42ba-8936-0788c4fcc0cb
- doc_id: `openfda_labels:cb2df7f7-fee8-42ba-8936-0788c4fcc0cb` | sections: 15
- automated checks: all pass
- first 300 characters: FETAL TOXICITY When pregnancy is detected, discontinue amlodipine and olmesartan medoxomil tablets as soon as possible (5.1). Drugs that act directly on the renin-angiotensin system can cause injury and death to the developing fetus (5.1). WARNING: FETAL TOXICITY See full prescribing information for
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 123. Ammonium Chloride, Antimony Potassium Tartrate, Arsenic Trioxide, Oyster Shell Calcium Carbonate, Crude, Lobelia Inflata, Sodium Sulfate, Spongia Officinalis Skeleton, Roasted, Phosphorus (Congestion Hp) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=97164607-bc12-44cc-84e8-f2ebc0783bd9
- doc_id: `openfda_labels:97164607-bc12-44cc-84e8-f2ebc0783bd9` | sections: 6
- automated checks: all pass
- first 300 characters: Temporarily relieves dry, barking cough, spasmodic cough.\*\* USES: Temporarily relieves dry, barking cough, spasmodic cough.\*\* ACTIVE INGREDIENTS (HPUS\*)- equal amounts of: Ammon Mur 30X, Antimon Tart 30X, Arsenicum Alb 30X, Calc Carb 30C, Lobelia Inf 30X, Nat Sulphuricum 30X, Spongia Tosta 30X,
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 124. Apis Mellifera, Clematis Recta Whole, Anemone Pulsatilla, Chimaphila Umbellata, Sus Scrofa Testicle, Chaste Tree, And Sepia Officinalis Juice (N-7) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=7ebe3a62-8f35-4cbe-815a-77e91c14f247
- doc_id: `openfda_labels:7ebe3a62-8f35-4cbe-815a-77e91c14f247` | sections: 7
- automated checks: all pass
- first 300 characters: Support for the Testicals. Support for the Testicals. INGREDIENTS Apis mellifica 6x, Clematis erecta 4x, Pulsatilla 5x, Chimaphila umbellata 4x, Orchic 6/12/30/60/200x, Agnus castus 4x, Sepia 10x, 20% alcohol in purified water. SUGGESTED DOSAGE One dropper under tongue two times daily. Acute symptom
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 125. Antimony Triiodide (Antimonium iodatum) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=141d6037-8728-bc6c-e063-6294a90a475c
- doc_id: `openfda_labels:141d6037-8728-bc6c-e063-6294a90a475c` | sections: 5
- automated checks: all pass
- first 300 characters: See symptoms on front panel. Relieves productive cough with thick mucus \* Antimonium iodatum 200CK HPUS Active ingredient\*\*: See product name on front panel (\*\*contains 0.443 mg of the active ingredient per pellet). Less than 10 -12 mg antimony per pellet Adults and children: At the onset of sy
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 126. Iris Versicolor, Solidago Virgaurea, Antimonium Crudum, Apis Mellifica, Arsenicum Album, Baptisia Tinctoria, Blatta Orientalis, Bromium, Bryonia, Candida Albicans, Carduus Benedictus, Cat Hair, Chelidonium Majus, Cinchona Officinalis, Dog Hair, Histaminum Hydrochloricum, House Dust, Ipecacuanha, Lycopodium Clavatum, Nux Vomica, Podophyllum Peltatum, Rhus Toxicodendron, Secale Cornutum, Silicea, Ustilago Maidis, Torula Cerevisiae. (Dust-Mold-Dander) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=9bb84bae-9019-ed76-e053-2a95a90a5c3e
- doc_id: `openfda_labels:9bb84bae-9019-ed76-e053-2a95a90a5c3e` | sections: 7
- automated checks: all pass
- first 300 characters: SECTION Formulated for associated symptoms such as labored breathing, congestion, sneezing, runny nose, watery eyes and skin irritations, OTC - PURPOSE SECTION Formulated for associated symptoms such as labored breathing, congestion, sneezing, runny nose, watery eyes and skin irritations. OTC - ACTI
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 127. Bos Taurus Adrenal Gland, Apis Mellifera, Arsenic Trioxide, Lytta Vesicatoria, Bos Taurus Lymph Vessel, Magnesium Phosphate, Dibasic Trihydrate, Toxicodendron Pubescens Leaf, Urtica Urens, Pyridoxine Hydrochloride, And Ascorbic Acid (D-105) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=1535cb47-b155-4ac4-af7d-b22ac8325403
- doc_id: `openfda_labels:1535cb47-b155-4ac4-af7d-b22ac8325403` | sections: 7
- automated checks: all pass
- first 300 characters: For allergic skin conditions, hives and rashes. For allergic skin conditions, hives and rashes. INGREDIENTS ACTIVE Adrenal 6/12x, Apis mellifica 12/30x, Arsenicum album 30x, Cantharis 12/30x, Lymph 6/12x, Magnesia phosphorica 6/12x, Rhus toxicodendron 12/30x, Urtica urens 12/30x, Vitamin B-6 3x, Vit
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 128. Emotional Rebalance (RPT-Sys) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=0e8768fe-c2ba-41e9-93ac-c142fae6e879
- doc_id: `openfda_labels:0e8768fe-c2ba-41e9-93ac-c142fae6e879` | sections: 6
- automated checks: all pass
- first 300 characters: RPT-Sys For the temporary relief of anxiety, confusion, memory loss, and depression. RPT-Sys Focuses on the vibrational and electrical balances to the body. RPT-Sys Apocynum Cannabinum 10X Lathyrus Sativus 10X, 20X Plantinum Metallicum 10X Asafoetida 6X Lecithin 10X, 20X Rhus Toxicodendron 5X, 10X B
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 129. Taraxacum Officinale Root, Verbena Hastata Top, Lactuca Virosa Leaf, Chamomile Flower Oil, Arabica Coffee Bean, And Scutellaria Lateriflora Whole (More Focus) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=a5583344-9be9-4c81-ab97-8ff5c9cf5af2
- doc_id: `openfda_labels:a5583344-9be9-4c81-ab97-8ff5c9cf5af2` | sections: 8
- automated checks: all pass
- first 300 characters: to help focus mental abilities and restore calm thinking. Active ingredients Purpose Taraxacum Officinale\* 6C Irritability, Impaired Thinking Verbena Hastata\* 12C Nervousness, Helps Brighten Mental Powers Lactuca Virosa\* 12C Great Restlessness, Difficulty Concentrating Coffea Cruda\* 30C For Rest
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 130. Arnica Montana, Calendula Officinalis, Hypericum Perf, Symphytum Off, Bellis Per, Ledum Palustre, Sulphuricum Ac, Calc Fluor, Ferrum Phos, Rhus Tox, Nat Sulphuricum (Injure Gel) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=8893c906-0dab-44ef-956b-b5427d4dbf7f
- doc_id: `openfda_labels:8893c906-0dab-44ef-956b-b5427d4dbf7f` | sections: 6
- automated checks: all pass
- first 300 characters: Temporarily relieves soreness and bruised feelings.\*\* USES: Temporarily relieves soreness and bruised feelings.\*\* ACTIVE INGREDIENTS (\*HPUS) - equal amounts of: Arnica Montana4X, 30C, Calendula Officinalis 4X, Hypericum Perf 4X, 30C, Symphytum Off 6X, Bellis Per 12X, Ledum Palustre 12X, Sulphur
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 131. Passiflora Incarnata, Glandula Suprarenalis Suis, Thyroidinum (Suis), Arnica Montana, Hypericum Perforatum, Lachesis Mutus, Muira Puama (Neurotone) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=5007c3b2-0552-439e-b47a-681ba4a23b40
- doc_id: `openfda_labels:5007c3b2-0552-439e-b47a-681ba4a23b40` | sections: 6
- automated checks: all pass
- first 300 characters: For temporary relief of numbness and tingling; stiffness in nape of the neck and shooting pains with tingling and burning pain and numbness.\*\* \*\*Claims based on traditional homeopathic practice, not accepted medical evidence. Not FDA evaluated. Arnica Montana - stiffness,\*\* Glandula Suprarenal
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 132. Arsenicum Album, Borrelia Burgdorferi Nosode, Chelidonium Majus, Coccus Cacti, Echinacea (Angustifolia), Hydrastis Canadensis, Lycopodium Clavatum, Nasturtium Aquaticum, Phosphorus, Rhus Tox, Taraxacum Officinale, Thymus (Suis), Thyroidinum (Suis), Trifolium Pratense, Urtica Dioica (LD Force HP) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=40016043-bd05-4ef2-b44b-ad73879815a1
- doc_id: `openfda_labels:40016043-bd05-4ef2-b44b-ad73879815a1` | sections: 6
- automated checks: all pass
- first 300 characters: For temporary relief of aches and pains of joints and muscles as a consequence of infection. INDICATIONS: For temporary relief of aches and pains of joints and muscles as a consequence of infection. ACTIVE INGREDIENTS: Arsenicum Album 30C, Borrelia Burgdorferi Nosode 30C, Chelidonium Majus 30C, Cocc
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 133. Hai-Chin-Sha (Lygodium Japonicum), Astragalus Membranaceous, Chin-Chien-Tsao (Lysimachia Christinae), Lobelia Inflata, Lycopodium Clavatum (Kidney Formula) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=ba8738b8-563f-4363-976c-af2c4c605d35
- doc_id: `openfda_labels:ba8738b8-563f-4363-976c-af2c4c605d35` | sections: 6
- automated checks: all pass
- first 300 characters: Aids in degenerative conditions of the kidneys.† †Claims based on traditional homeopathic practice, not accepted medical evidence. Not FDA evaluated. Aids in degenerative conditions of the kidneys.† †Claims based on traditional homeopathic practice, not accepted medical evidence. Not FDA evaluated. 
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 134. Cupric Acetate, Ipecac, Magnesium Phosphate, Dibasic Trihydrate, Drosera Rotundifolia, Atropa Belladonna, Hyoscyamus Niger, Onion, Corallium Rubrum Exoskeleton, And Lobaria Pulmonaria (D-9) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=15cb964d-086f-40a6-8056-5f149f04ab4c
- doc_id: `openfda_labels:15cb964d-086f-40a6-8056-5f149f04ab4c` | sections: 7
- automated checks: all pass
- first 300 characters: Spasmodic cough. Spasmodic cough. INGREDIENTS ACTIVE Cuprum aceticum 6x, Ipecacuanha 6x, Magnesia phosphorica 30x, Drosera rotundifolia 6x, Belladonna 4x, Hyoscyamus niger 4x, Allium cepa 4x, Corallium rubrum 12x, Sticta pulmonaria 4x INACTIVE 20% alcohol in purified water. SUGGESTED DOSAGE One drop
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 135. Belladonna, Cuprum Aceticum, Drosera, Grindelia, Ipecac, Lobelia Inflata, Naphthalinum, Yerba Santa (Bm Bm13 Drops) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=54103c3b-1974-b550-e063-6394a90a3145
- doc_id: `openfda_labels:54103c3b-1974-b550-e063-6394a90a3145` | sections: 6
- automated checks: all pass
- first 300 characters: \* Helps temporarily relieve: cough and throat irritation; and respiratory discomfort with mucus or congestion. Belladonna 4X (HPUS)......sudden cough, throat irritation Cupr acet 6X (HPUS)......coughing fits, chest discomfort Drosera 3X (HPUS)......dry cough, night cough, throat irritation Grindeli
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 136. Avena Sativa Flowering Top - Canakinumab - Chamomile - Helleborus Niger Root - Melatonin - Melissa Officinalis - Pulsatilla Vulgaris - Serotonin - Strychnos Ignatii Seed - Sus Scrofa Pineal Gland - Valerian - (Guna-Sleep) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=62c57cc4-28c9-406f-821d-1d48370968f2
- doc_id: `openfda_labels:62c57cc4-28c9-406f-821d-1d48370968f2` | sections: 6
- automated checks: all pass
- first 300 characters: Take 15 minutes before meals. Temporary relief of: Difficulty falling asleep Avena sativa 6C Helps relaxation, sleep Chamomilla 6C Helps relaxation, sleep Helleborus niger 6C Emotional stress Ignatia amara 6C Emotional stress Interleukin 1 beta 4C Helps sleep Melatonin 4C Helps relaxation, sleep Mel
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 137. Avobenzone, Homosalate, Octocrylene, Oxybenzone (Skin Balancing Ultra Sheer Daily Defence SPF 30 Paulas Choice) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=3bf31626-5580-457b-8a59-cc37f4ab0767
- doc_id: `openfda_labels:3bf31626-5580-457b-8a59-cc37f4ab0767` | sections: 6
- automated checks: all pass
- first 300 characters: Stop use and ask a doctor if rash occurs Uses Helps prevent sunburn If used as directed with other sun protection measures (see Directions ), decreases the risk of skin cancer and early skin aging caused by sun. Active Ingredients Purpose Avobenzone 3.0% ........... Sunscreen Homosalate 7.0% .......
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 138. Avobenzone, Homosalate, Octisalate. Octocrylene, And Oxybenzone (Obagi Skintrinsiq Antioxidant Protocol) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=53023b16-8d64-4dfc-bc75-b4f248425c4d
- doc_id: `openfda_labels:53023b16-8d64-4dfc-bc75-b4f248425c4d` | sections: 9
- automated checks: all pass
- first 300 characters: helps prevent sunburn if used as directed with other sun protection measures (see Directions ), decreases the risk of skin cancer and early skin aging caused by the sun Active ingredients Purpose Avobenzone 3% Sunscreen Homosalate 8% Sunscreen Octisalate 5% Sunscreen Octocrylene 2.79% Sunscreen Oxyb
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 139. Mangifera Indica Leaf Extract,Stem Banana Extract,White Mulberry (Morus Alba) Leaf Extract (St. Paul Brands GlucoTrojan) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=a4a83a79-7914-4ed1-9439-a9da6e86fb94
- doc_id: `openfda_labels:a4a83a79-7914-4ed1-9439-a9da6e86fb94` | sections: 3
- automated checks: all pass
- first 300 characters: Take 2 capsules per day before a meal, one before lunch and one before dinner. If you are pregnant, may become pregnant or are breast feeding, consult your healthcare professional before using this product. Do not use if tamper-evident seal is broken or missing. Keep Out of The Reach of Children.
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 140. Nightshade Mix (Nightshade Mix 1011) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=8ccfb31a-1337-442a-b79c-1be94bb3da2a
- doc_id: `openfda_labels:8ccfb31a-1337-442a-b79c-1be94bb3da2a` | sections: 7
- automated checks: all pass
- first 300 characters: For the temporary relief of gas, bloating, diarrhea, and itching of the nose or throat due to sensitivity to nightshades.\* \*Claims based on traditional homeopathic practice, not accepted medical evidence. Not FDA evaluated. ACTIVE INGREDIENTS Adrenal 6X ACTH 6X, 30X Histaminum hydrochloricum 12X L
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 141. Methyl Salicylate, Menthol, Camphor (Mentol Chino Forte) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=12652c98-e2a8-21fc-e063-6394a90a94cb
- doc_id: `openfda_labels:12652c98-e2a8-21fc-e063-6394a90a94cb` | sections: 8
- automated checks: all pass
- first 300 characters: AGAINST ECZEMA, PIMPLES AND OTHER SKIN CONDITIONS USES AGAINST ECZEMA, PIMPLES AND OTHER SKIN CONDITIONS. TREATMENT OF DERMATOPHYTE INFECTIONS. SKIN TREATMENT ACTIVE INGREDIENTS BENZOIC ACID 6.0 g, SALYCYLIC ACID 2.5 g, SULFUR 4.6 g WASH THE AFFECT PART WITH WARM WATER AND SOAP. APPLY THE OINMENT LI
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 142. Beta Vulgaris, Boldo, Calcarea Fluorica, Calcarea Phosphorica, Carduus Benedictus, Chelidonium Majus, Coffea Tosta, Equisetum Arvense, Germanium Sesquioxide, Ginkgo Biloba, Hypericum Perforatum, Kali Muriaticum, Kali Phosphoricum, Kali Sulphuricum, Petroselinum Sativum, Silicea, Taraxacum Officinale (Hydration Complex) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=f60a2ab8-4146-4995-9bc6-be2660b17540
- doc_id: `openfda_labels:f60a2ab8-4146-4995-9bc6-be2660b17540` | sections: 6
- automated checks: all pass
- first 300 characters: • For the temporary relief of symptoms including: • infrequent urination • back pain • headache • dry mouth • low energy These statements are based upon homeopathic principles. They have not been reviewed by the Food and Drug Administration. Beta Vulgaris – Low Energy, Boldo – Infrequent Urination, 
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 143. Visual Detox (Visual Detox 6037) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=cb9b4288-17cd-4b9a-9b5d-45ef604238ad
- doc_id: `openfda_labels:cb9b4288-17cd-4b9a-9b5d-45ef604238ad` | sections: 7
- automated checks: all pass
- first 300 characters: Temporarily relieves occasional blurred or distorted vision, seeing floaters or spots, sensitivity to light, or red, painful eyes or eyelids\* \*Claims based on traditional homeopathic practice, not accepted medical evidence. Not FDA evaluated. ACTIVE INGREDIENTS Taurine 6X Lutein/Zeaxanthin 6X, 8X 
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 144. Bispit Liver Restoration Tablets (Bispit Canada Ltd.) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=36e35682-57cb-f60f-e063-6394a90aafa5
- doc_id: `openfda_labels:36e35682-57cb-f60f-e063-6394a90aafa5` | sections: 6
- automated checks: all pass
- first 300 characters: This product is suitable for people at high risk ofchemical liver injury or those who have alreadydeveloped symptoms of injury, including: 1. Long-term medication usersPatients who need to take liver-toxic drugs for a long timesuch as antibiotics, anti-tuberculosis drugs, and anti-tumordrugs. 2.Occu
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 145. Brimonidine (Brimonidine Tartrate) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=9f17bf0c-d880-4328-bf92-00ac81d02fd1
- doc_id: `openfda_labels:9f17bf0c-d880-4328-bf92-00ac81d02fd1` | sections: 16
- automated checks: all pass
- first 300 characters: Brimonidine topical gel, 0.33% is an alpha adrenergic agonist indicated for the topical treatment of persistent (nontransient) erythema of rosacea in adults 18 years of age or older. Brimonidine topical gel, 0.33% is an alpha adrenergic agonist indicated for the topical treatment of persistent (nont
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 146. Calc Carb, Nux Vom, Sepia, Spongia, Sulphur (Hormoslim) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=d5f3c0a7-248b-8c0b-e053-2a95a90a0d30
- doc_id: `openfda_labels:d5f3c0a7-248b-8c0b-e053-2a95a90a0d30` | sections: 7
- automated checks: all pass
- first 300 characters: \*: Uses\*: Supports female hormones during times of stress, when used along with a healthy diet and excercise. \*Claims based on traditional homeopathic practice, not accepted medical evidence. Not FDA evaluated. Supports female hormones during times of stress\* \*Claims based on traditinoal homeop
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 147. Calc Fluor, Calc Phos, Calc Sulph, Ferrum Phos, Kali Mur, Kali Phos, Kali Sulph, Mag Phos, Nat Mur, Nat Phos, Nat Sulph, Silicea, Zinc Gluc (Dr. Talbots Vital 12) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=c10bb804-8169-63da-e053-2a95a90a8306
- doc_id: `openfda_labels:c10bb804-8169-63da-e053-2a95a90a8306` | sections: 7
- automated checks: all pass
- first 300 characters: Provides a daily supply of Vital 12 cell salts to help balance and support overall cell functions. Provides zinc and elderberry to help with immune support.+ Indication & Usage Provides a daily supply of Vital 12 cell salts to help balance and support overall cell functions. Provides zinc and elderb
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 148. Mycoplasma Pneumoniae, Proteus (Vulgaris), Candida Albicans, Colibacillinum Cum Natrum Muriaticum, Mycobacterium Paratuberculosis, Pasteurellosis (Pasteurella Multocida), Pneumococcinum, Thuja Occidentalis, Mycobacterium Avium Paratuberculosis, Phytolacca Decandra, Legionella Pneumophila, Shigella Sonnei (BioTox Bac 3) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=29f1cba2-0bb6-43bf-a630-afc8fcb1ec81
- doc_id: `openfda_labels:29f1cba2-0bb6-43bf-a630-afc8fcb1ec81` | sections: 6
- automated checks: all pass
- first 300 characters: For temporary relief of fever and chills. Promotes a productive wet cough and the coughing up of phlegm. expectorant. Helps relieve the presence of mucus in the stool and loose stools. INDICATIONS: For temporary relief of fever and chills. Promotes a productive wet cough and the coughing up of phleg
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 149. Uncaria Tomentosa (Cats Claw) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=7a6dc6f6-4471-46f8-810f-6757fac9bf6b
- doc_id: `openfda_labels:7a6dc6f6-4471-46f8-810f-6757fac9bf6b` | sections: 6
- automated checks: all pass
- first 300 characters: May temporarily relieve symptoms associated with exhaustion, joint pain, and immune weakness.\*\* \*\*Claims based on traditional homeopathic practice, not accepted medical evidence. Not FDA evaluated. May temporarily relieve symptoms associated with exhaustion, joint pain, and immune weakness.\*\* 
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 150. Hepar Magnesium 4 - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=ce86084a-a83d-4960-b70e-7f41cbc0b005
- doc_id: `openfda_labels:ce86084a-a83d-4960-b70e-7f41cbc0b005` | sections: 5
- automated checks: all pass
- first 300 characters: Directions: FOR ORAL USE ONLY. Use: Temporary relief of headache. Active Ingredients: Hepar oryctolagus (Liver) 4X, Magnesium hydroxydatum (Magnesium hydroxide) 4X Take 3-4 times daily. Ages 12 and older: 10 drops. Ages 2-11: 5 drops. Under age 2: Consult a doctor. Claims based on traditional homeop
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 151. Ceanothus Americanus, Argentum Nitricum, Condurango, Hydrastis Canadensis, Momordica Balsamina, Pulsatilla (Pratensis), Bile Duct (Suis), Colon (Suis), Duodenum (Suis), Esophagus (Suis), Eye (Suis), Gallbladder (Suis), Ileum (Suis), Intestine (Suis), Ipecacuanha, Jejunum (Suis), Kali Bichromicum, Lung (Suis), Mucosa Nasalis Suis, Natrum Oxalaceticum, Oral Mucosa (Suis), Pancreas Suis, Phosphorus, Rectal Mucosa (Suis), Stomach (Suis), Sulphur, Veratrum Album, Mannose, Anacardium Orientale, Kreosotum, (Matrix Support) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=bae2c721-44e8-4f88-92da-66e8ae03ada0
- doc_id: `openfda_labels:bae2c721-44e8-4f88-92da-66e8ae03ada0` | sections: 6
- automated checks: all pass
- first 300 characters: • For the temporary relief of symptoms including: • occasional diarrhea • occasional constipation • headache • gas • congestion • irritated eyes • indigestion • bladder support These statements are based upon homeopathic principles. They have not been reviewed by the Food and Drug Administration. An
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 152. Rectum Drops (Rectum Drops 9633) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=c25ae7c5-0a15-4bcd-b3d6-377f7734c05c
- doc_id: `openfda_labels:c25ae7c5-0a15-4bcd-b3d6-377f7734c05c` | sections: 7
- automated checks: all pass
- first 300 characters: For the temporary relief of constipation or a change in bowel habits, bloating, flatulence, or mild abdominal discomfort.\* \*Claims based on traditional homeopathic practice, not accepted medical evidence. Not FDA evaluated. ACTIVE INGREDIENTS Rectum 12X Place drops under tongue 30 minutes before/a
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 153. Chelidonium Majus, Iodium, Lycopus Virginicus, Ginkgo Biloba, Pinus Sylvestris, Fucus Vesiculosus, Spongia Tosta, Germanium Sesquioxide, Hypophysis Suis, Thyroidinum (Suis), Cysteinum, Manganese Gluconate, Alpha-Ketoglutaricum Acidum, Calcarea Carbonica, Ferrum Iodatum, Fumaricum Acidum, Kali Iodatum, Natrum Oxalaceticum, Pulsatilla (Vulgaris), Argentum Metallicum, Aurum Metallicum, Cuprum Metallicum, Eugenol, Formalinum, Lidocaine, Mercurius Solubilis, Molybdenum Metallicum, Niccolum Metallicum, (Oligo Bio Iodine) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=2f4f53a9-6294-4014-9898-72023b9506f5
- doc_id: `openfda_labels:2f4f53a9-6294-4014-9898-72023b9506f5` | sections: 6
- automated checks: all pass
- first 300 characters: For temporary relief of fatigue, muscular weakness, weak pulse, tendency to faint, cold hands & feet, low blood pressure, nervous tremor of limbs & sensitive to cold. INDICATIONS: For temporary relief of fatigue, muscular weakness, weak pulse, tendency to faint, cold hands & feet, low blood pressure
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 154. Chlophedianol Hcl, Dexchlorpheniramine Maleate (VanaCof 2) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=0c7c6756-abb2-c10c-e063-6394a90a9863
- doc_id: `openfda_labels:0c7c6756-abb2-c10c-e063-6394a90a9863` | sections: 11
- automated checks: all pass
- first 300 characters: ■ temporarily relieves these symptoms due to the common cold, hay fever (allergic rhinitis) or other upper respiratory allergies: ■ runny nose ■ sneezing ■ itching of the nose or throat ■ itchy, watery eyes ■ cough due to minor throat and bronchial irritation Cough Suppressant Antihistamine Active i
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 155. Aesculus Hippocastanum, Collinsonia Canadensis (H-Varicose Veins Formula) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=a54bbdaf-8dcc-4a5d-8ea3-ffc47abfba3f
- doc_id: `openfda_labels:a54bbdaf-8dcc-4a5d-8ea3-ffc47abfba3f` | sections: 8
- automated checks: all pass
- first 300 characters: For the temporary relief of varicose vein symptoms such as minor aching and swelling in legs. Aesculus hippocastanum-12C HPUS (varicose veins), Collinsonia canadensis -12C HPUS (vascular engorgement) The letters ‘HPUS’ indicate that the components in this product are officially monographed in the Ho
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 156. Crizotinib (Xalkori) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=2a51b0de-47d6-455e-a94c-d2c737b04ff7
- doc_id: `openfda_labels:2a51b0de-47d6-455e-a94c-d2c737b04ff7` | sections: 14
- automated checks: all pass
- first 300 characters: XALKORI is a kinase inhibitor indicated for the treatment of • adult patients with metastatic non-small cell lung cancer (NSCLC) whose tumors are anaplastic lymphoma kinase (ALK) or ROS1-positive as detected by an FDA-approved test. ( 1.1 , 2.1 ) • pediatric patients 1 year of age and older and youn
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 157. Turmeric Kojic Acid (FluMisch Turmeric Kojic Acid Facial Cleanser) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=2dee6804-1afd-a539-e063-6294a90a7567
- doc_id: `openfda_labels:2dee6804-1afd-a539-e063-6294a90a7567` | sections: 9
- automated checks: all pass
- first 300 characters: For cleansing facial skin facial cleansing TURMERIC & KOJIC ACID Pump an adequate amount of the mousse into your hands. The rich foam will form instantly Gently massage the foam onto damp skin in circular motions, focusing on areas prone to dirt and oil, like the forehead, nose, and chin Rinse thoro
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 158. Desonide (Desonide Ointment, 0.05%) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=6cea3912-23ae-45f3-b535-6fea29c7594f
- doc_id: `openfda_labels:6cea3912-23ae-45f3-b535-6fea29c7594f` | sections: 11
- automated checks: all pass
- first 300 characters: Desonide cream, 0.05% and desonide ointment, 0.05% are low potency corticosteroids indicated for the relief of the inflammatory and pruritic manifestations of corticosteroid responsive dermatoses. It should not be used for longer than two weeks unless directed by a physician. Desonide cream, 0.05% o
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 159. Dextrose Monohydrate, Sodium Chloride (Dextrose And Sodium Chloride) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=b825c9c4-f2fb-4a4a-9d8c-fb020ad07e93
- doc_id: `openfda_labels:b825c9c4-f2fb-4a4a-9d8c-fb020ad07e93` | sections: 14
- automated checks: all pass
- first 300 characters: 2.5% Dextrose and 0.45% Sodium Chloride Injection is indicated as a source of water, electrolytes and calories. 2.5% Dextrose and 0.45% Sodium Chloride Injection is indicated as a source of water, electrolytes and calories. ( 1 ) Only for intravenous infusion. ( 2.1 ) See full prescribing informatio
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 160. Dextrose, Sodium Chloride, And Potassium Chloride (Potassium Chloride in Dextrose and Sodium Chloride) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=59ccc717-c374-41c0-be58-9647df881160
- doc_id: `openfda_labels:59ccc717-c374-41c0-be58-9647df881160` | sections: 13
- automated checks: all pass
- first 300 characters: These intravenous solutions are indicated for use in adults and pediatric patients as sources of electrolytes, calories and water for hydration. These solutions are for intravenous use only. Dosage is to be directed by a physician and is dependent upon age, weight, clinical condition of the patient 
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 161. Monobasic Sodium Phosphate And Dibasic Sodium Phosphate (Potassium Phosphates) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=e2fcc382-6fac-4438-ad02-ebc8528dd59a
- doc_id: `openfda_labels:e2fcc382-6fac-4438-ad02-ebc8528dd59a` | sections: 14
- automated checks: all pass
- first 300 characters: WARNING: ACUTE PHOSPHATE NEPHROPATHY There have been rare, but serious reports of acute phosphate nephropathy in patients who received oral sodium phosphate products, including Monobasic Sodium Phosphate and Dibasic Sodium Phosphate Tablets, for colon cleansing prior to colonoscopy. Some cases have 
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 162. Diclofenac Epolamine (Licart) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=d7bfe17d-e88e-4792-bfba-cea56ed96c3b
- doc_id: `openfda_labels:d7bfe17d-e88e-4792-bfba-cea56ed96c3b` | sections: 15
- automated checks: all pass
- first 300 characters: RISK OF SERIOUS CARDIOVASCULAR and GASTROINTESTINAL EVENTS WARNING: RISK OF SERIOUS CARDIOVASCULAR and GASTROINTESTINAL EVENTS See full prescribing information for complete boxed warning. Nonsteroidal anti-inflammatory drugs (NSAIDs) cause an increased risk of serious cardiovascular thrombotic event
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 163. Euphorbium Combination (Euphorbium Combination 9255) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=ff642588-439e-4e79-8c7b-3d388938eca5
- doc_id: `openfda_labels:ff642588-439e-4e79-8c7b-3d388938eca5` | sections: 7
- automated checks: all pass
- first 300 characters: For the temporary relief of runny nose, nasal congestion, headache, or mild facial or ear pain due to a cold, hay fever, or other upper respiratory allergies.\* \*Claims based on traditional homeopathic practice, not accepted medical evidence. Not FDA evaluated. ACTIVE INGREDIENTS Plantago major 3X 
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 164. Echinacea Purpurea, Wood Creosote, Thuja Occidentalis Leafy Twig (Organic And Plant-Based Vulvovaginal Care) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=3754fddb-82f1-9ca7-e063-6294a90ab3da
- doc_id: `openfda_labels:3754fddb-82f1-9ca7-e063-6294a90ab3da` | sections: 11
- automated checks: all pass
- first 300 characters: For the relief of symptoms associated with vaginal yeast infection, including: irritation burning itching discharge. Purpose Relieve symptoms of vaginal yeast infection Active ingredients Echinacea purpurea 12X HPUS Kreosotum 12X HPUS Thuja occidentalis 12X HPUS Purpose Purpose Relieve symptoms of v
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 165. Ethanolamine Oleate (Ethamolin) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=a9c1d8c5-443e-400e-a42c-16a25fb47231
- doc_id: `openfda_labels:a9c1d8c5-443e-400e-a42c-16a25fb47231` | sections: 10
- automated checks: all pass
- first 300 characters: ETHAMOLIN Injection is indicated for the treatment of patients with esophageal varices that have recently bled, to prevent rebleeding. ETHAMOLIN is not indicated for the treatment of patients with esophageal varices that have not bled. There is no evidence that treatment of this population decreases
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 166. Norelgestromin And Ethinyl Estradiol (Zafemy) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=10fa1458-c8ed-4197-922a-1ba7271d2b02
- doc_id: `openfda_labels:10fa1458-c8ed-4197-922a-1ba7271d2b02` | sections: 17
- automated checks: all pass
- first 300 characters: CIGARETTE SMOKING AND SERIOUS CARDIOVASCULAR EVENTS and CONTRAINDICATED IN WOMEN WITH A BMI \|GTE 30 kg/m2 • Cigarette Smoking and Serious Cardiovascular Events Cigarette smoking increases the risk of serious cardiovascular events from hormonal contraceptive use. This risk increases with age, partic
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 167. Sunscreen (Lapcos Daily Sunscreen Spf 50) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=337c3528-5739-6b4a-e063-6294a90a3cb4
- doc_id: `openfda_labels:337c3528-5739-6b4a-e063-6294a90a3cb4` | sections: 9
- automated checks: all pass
- first 300 characters: Helps prevent sunburn If used as directed with other sun protection measures (see Directions), decreases the risk of skin cancer and early skin aging caused by the sun. Helps prevent sunburn. If used as directed with other sun protection measures (see Directions), decreases the risk of skin cancer a
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 168. Ferric Oxide Red (Calamine) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=1a03331e-3676-451c-be22-9a547e8ae6e2
- doc_id: `openfda_labels:1a03331e-3676-451c-be22-9a547e8ae6e2` | sections: 9
- automated checks: all pass
- first 300 characters: dries the oozing and weeping of poison: ivy oak sumac Skin Protectant Active ingredients Calamine 8% Zinc oxide 8% shake well before using apply as needed For external use only When using this product do not get into eyes and ask a doctor if condition worsens symptoms last more than 7 days or clear 
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 169. Filgrastim-Aafi (Nivestym) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=d23ab39c-b6ec-41cf-a529-9dd2852c9d9a
- doc_id: `openfda_labels:d23ab39c-b6ec-41cf-a529-9dd2852c9d9a` | sections: 14
- automated checks: all pass
- first 300 characters: NIVESTYM is a leukocyte growth factor indicated to • Decrease the incidence of infection‚ as manifested by febrile neutropenia‚ in patients with nonmyeloid malignancies receiving myelosuppressive anti-cancer drugs associated with a significant incidence of severe neutropenia with fever. ( 1.1 ) • Re
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 170. Sodium Fluoride (Fluoride) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=0df8f1aa-f3ef-9f59-e063-6294a90a0666
- doc_id: `openfda_labels:0df8f1aa-f3ef-9f59-e063-6294a90a0666` | sections: 13
- automated checks: all pass
- first 300 characters: For once daily self-applied systemic use as a dental caries preventive in pediatric patients. It has been established that ingestion of fluoridated drinking water (1 ppm F¯) during the period of tooth development results in a significant decrease in the incidence of dental caries. Sodium Fluoride Ch
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 171. Glorysmile Toothpaste. - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=2ef48156-904d-e42a-e063-6394a90a3cd0
- doc_id: `openfda_labels:2ef48156-904d-e42a-e063-6394a90a3cd0` | sections: 10
- automated checks: all pass
- first 300 characters: Those who want to clean and whiten their teeth. Teeth cleaning Active Ingredient Sodium Fluoride Sodium Gluconate 1. Apply 2 pumps to a soft bristle toothbrush. 2. Gently brush it a circular motion for 2 minutes. 3. Expel excess and rinse mouth after use, do not swallow. Product is not intended for 
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 172. Follitropin (Gonal-f RFF Redi-ject) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=b6d11c45-b502-478e-bb28-2ff596ea259c
- doc_id: `openfda_labels:b6d11c45-b502-478e-bb28-2ff596ea259c` | sections: 14
- automated checks: all pass
- first 300 characters: GONAL-f ® RFF Redi-ject ® is a prefilled gonadotropin-containing auto-injection device indicated for: Induction of ovulation and pregnancy in oligo-anovulatory women in whom the cause of infertility is functional and not due to primary ovarian failure ( 1.1 ) Development of multiple follicles in ovu
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 173. Gadobutrol (Gadavist) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=c0dd1618-0bb3-4974-846b-e5afc2311ae6
- doc_id: `openfda_labels:c0dd1618-0bb3-4974-846b-e5afc2311ae6` | sections: 14
- automated checks: all pass
- first 300 characters: RISK ASSOCIATED WITH INTRATHECAL USE and NEPHROGENIC SYSTEMIC FIBROSIS Risk Associated with Intrathecal Use Intrathecal administration of gadolinium-based contrast agents (GBCAs) can cause serious adverse reactions including death, coma, encephalopathy, and seizures. Gadobutrol injection is not appr
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 174. Glycerin 37.5%, Lanolin 12.5%, Lidocaine 4%, Zinc Oxide 5% (Doctor Butler Hemorrhoid and Fissure Advanced Formula) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=d2a769e2-afd0-aed2-e053-2995a90ad429
- doc_id: `openfda_labels:d2a769e2-afd0-aed2-e053-2995a90ad429` | sections: 9
- automated checks: all pass
- first 300 characters: helps relieve the local or anorectal itching and discomfort associated with hemorrhoids Protectant Protectant Analgesic (pain relief) Astringent Active ingredients Glycerin 37.5% Lanolin 12.5% Lidocaine 4.0% Zinc Oxide 5.0% adults; when practical, cleanse the affected area by patting or blotting wit
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 175. Herpes Simplex 1 Dna, Herpes Simplex 2 Dna, Herpes Simplex I Nosode, Herpes Simplex Ii Nosode (Hers Homo) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=5b8f13e8-04cb-4f04-9b22-7ee9d67d377f
- doc_id: `openfda_labels:5b8f13e8-04cb-4f04-9b22-7ee9d67d377f` | sections: 6
- automated checks: all pass
- first 300 characters: • For the temporary relief of symptoms including: • mouth sores • lip sores • gums sores • fever blisters • fever These statements are based upon homeopathic principles. They have not been reviewed by the Food and Drug Administration. DNA - Mouth Sores, Lip Sores, Gum Sores, Fever Blisters, Fever, H
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 176. L-Glycine High (L-Glycine High 7408) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=68e19e5b-0256-4052-8d79-2825e0219dbb
- doc_id: `openfda_labels:68e19e5b-0256-4052-8d79-2825e0219dbb` | sections: 7
- automated checks: all pass
- first 300 characters: For the temporary relief of tiredness, general weakness, muscle fatigue, sleep disturbance, minor joint pain or stiffness, diminished memory, mood changes, or indigestion.\* \*Claims based on traditional homeopathic practice, not accepted medical evidence. Not FDA evaluated. ACTIVE INGREDIENTS L-Gly
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 177. Hexylresorcinol (S.T.37) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=7d7acca2-aa8a-5272-e813-faab039cc798
- doc_id: `openfda_labels:7d7acca2-aa8a-5272-e813-faab039cc798` | sections: 12
- automated checks: all pass
- first 300 characters: temporarily relieves: minor irritations of the mouth minor pain in the mouth sore mouth sore throat first aid to help prevent skin infection in minor cuts, scrapes, and burns Active Ingredient Purposes Hexylresorinol 0.1% Oral Pain Reliever First aid antiseptic Active Ingredient Purposes Hexylresori
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 178. Homosalate, Octocrylene,Octisalate,Avobenzone (Abib No White Cast SPF Gift Set) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=537420bb-9fd8-0649-e063-6394a90aa8cf
- doc_id: `openfda_labels:537420bb-9fd8-0649-e063-6394a90aa8cf` | sections: 9
- automated checks: all pass
- first 300 characters: helps prevent sunburn if used as directed with other sun protection measures ( see Directions ), decreases the risk of skin cancer and early skin aging caused by the sun Uses help prevent sunburn if used as directed with other sun protection measures ( see Directions ), deacreases the risk of skin c
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 179. Human Albumin Microspheres And Perflutren (Optison Perflutren Protein-Type A Microspheres) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=46bcf276-d423-408a-a410-f11383406a94
- doc_id: `openfda_labels:46bcf276-d423-408a-a410-f11383406a94` | sections: 12
- automated checks: all pass
- first 300 characters: SERIOUS CARDIOPULMONARY REACTIONS Serious cardiopulmonary reactions, including fatalities, have occurred uncommonly during or following perflutren-containing microsphere administration. Most serious reactions occur within 30 minutes of administration \[see Warnings and Precautions (5.1) \]. Assess a
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 180. Herpes Zoster Nosode (Herz Homo) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=9bf87427-dc94-4191-b6ec-2759f7e03fef
- doc_id: `openfda_labels:9bf87427-dc94-4191-b6ec-2759f7e03fef` | sections: 6
- automated checks: all pass
- first 300 characters: • For the temporary relief of symptoms including: • itching • tingling • painful rash of body • rash on side of face • painful rash on face These statements are based upon homeopathic principles. They have not been reviewed by the Food and Drug Administration. Herpes Zoster Nosode - Itching, Tinglin
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 181. Titanium Dioxide (EELHOE Body Coverage Perfector) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=5610c3b7-456b-3bc1-e063-6394a90a3fa8
- doc_id: `openfda_labels:5610c3b7-456b-3bc1-e063-6394a90a3fa8` | sections: 9
- automated checks: all pass
- first 300 characters: 1. Cleanse the skin. 2. Apply liberally On the areas you want to touch up, using a hand or body brush, working upwards and outwards. Allow product to dry for 10 minutes, and if desired, apply another coat for added coverage, allowing each coat to dry for 10 minutes. 3. Remove excess product by wipin
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 182. Methenamine, Sodium Phosphate, Monobasic, Methylene Blue, And Hyoscyamine Sulfate (Urogesic Blue) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=f650dd78-615c-42d3-9b2d-3a989039d80c
- doc_id: `openfda_labels:f650dd78-615c-42d3-9b2d-3a989039d80c` | sections: 12
- automated checks: all pass
- first 300 characters: UROGESIC-BLUE™ is indicated for the treatment of symptoms of irritative voiding. Indicated for the relief of local symptoms, such as hypermotility which accompany lower urinary tract infections and as antispasmodic. Indicated for the relief of urinary tract symptoms caused by diagnostic procedures. 
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 183. Interleukin-3 (Guna-Il 3) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=5be3096f-9046-457c-b7ba-767ffe74c07a
- doc_id: `openfda_labels:5be3096f-9046-457c-b7ba-767ffe74c07a` | sections: 7
- automated checks: all pass
- first 300 characters: Take 15 minutes before meals. USES HEMATOPOIESIS SUPPORT ACTIVE INGREDIENTS/PURPOSE INTERLEUKIN-3 4C HEMATOPOIESIS SUPPORT Take 15 minutes before meals Adults and children 12 years and older 20 drops twice a day in a little water. Hold in the mouth for about 30 seconds then swallow. Children between
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 184. Heating Pad (iShanCare Heating Pad) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=31142e15-aab1-5787-e063-6394a90a16d4
- doc_id: `openfda_labels:31142e15-aab1-5787-e063-6394a90a16d4` | sections: 8
- automated checks: all pass
- first 300 characters: Directions Take Heating Patch out ofpackaging.Use immediatelyafter package is opened. Remove paper from theadhesive backing. Place on pain area againsunderwear/clothing, not against skin. USES Provides temporary relief from menstrual cramp pain and associated muscle aches. Active ingredient Iron Pow
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 185. Lanadelumab-Flyo (Takhzyro) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=15f99d8c-efe7-4f7d-aa20-0d0f1e30c6e8
- doc_id: `openfda_labels:15f99d8c-efe7-4f7d-aa20-0d0f1e30c6e8` | sections: 15
- automated checks: all pass
- first 300 characters: TAKHZYRO ® is indicated for prophylaxis to prevent attacks of hereditary angioedema (HAE) in adult and pediatric patients aged 2 years and older. TAKHZYRO is a plasma kallikrein inhibitor (monoclonal antibody) indicated for prophylaxis to prevent attacks of hereditary angioedema (HAE) in adult and p
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 186. Lidocaine, Menthol (Maximum Strenght Lidocaine plus Menthol Pain Relief Patch) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=bd34a5bd-af5a-680f-e053-2995a90abc74
- doc_id: `openfda_labels:bd34a5bd-af5a-680f-e053-2995a90abc74` | sections: 10
- automated checks: all pass
- first 300 characters: Temporarily relieves minor pain. Uses Temporarily relieves minor pain. Active Ingredients Lidocaine 4.0% . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . Topical Anesthetic Menthol 1.0% . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . Topical Anesthetic Directions Adults and ch
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 187. Lidocaine And Menthol (Orvexa) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=6760e4cf-475a-4f3e-a700-3f30221daffb
- doc_id: `openfda_labels:6760e4cf-475a-4f3e-a700-3f30221daffb` | sections: 11
- automated checks: all pass
- first 300 characters: Lidocaine patch 5% is indicated for relief of pain associated with post-herpetic neuralgia. It should be applied only to intact skin . Menthol 6%------------------------------------------------------------Topical Analgesic HealthWise Roll-on Menthol Pain Relief Gel HealthWise Rol-on Menthol Pain Rel
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 188. Lilium Tig (Lilium tigrinum) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=1a22d00c-b352-7eed-e063-6394a90ae973
- doc_id: `openfda_labels:1a22d00c-b352-7eed-e063-6394a90ae973` | sections: 9
- automated checks: all pass
- first 300 characters: Condition listed above or as directed by the physician USES USES: Temporary Relief - Muscular Cramps\* \* Claims based on traditional homeopathic practice, not accepted medical evidence. Not FDA evaluated. ACTIVE INGREDIENT LILIUM TIG HPUS 1X and higher Adults: Mix 4-6 drops in 1/2 cup of water, tak
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 189. Glycerin (EELHOE 5 Days Tooth Powder) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=42f98b14-d1d5-4af8-e063-6294a90a8f67
- doc_id: `openfda_labels:42f98b14-d1d5-4af8-e063-6294a90a8f67` | sections: 9
- automated checks: all pass
- first 300 characters: 1. Pour an appropriate amount of teeth whitening powder (1/2 to 3/4 teaspoons) into a cup of warm water. Do not use too much whitening powder, as it may irritate your teeth and gums. 2. Mix the whitening powder and water evenly with a stirring rod or toothbrush until there are no lumps. 3. Dip your 
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 190. Primidone (Mysoline) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=ad8b50e2-e797-4326-a57e-d254da85b6b9
- doc_id: `openfda_labels:ad8b50e2-e797-4326-a57e-d254da85b6b9` | sections: 10
- automated checks: all pass
- first 300 characters: Primidone, used alone or concomitantly with other anticonvulsants, is indicated in the control of grand mal, psychomotor, and focal epileptic seizures. It may control grand mal seizures refractory to other anticonvulsant therapy. Adult Dosage Patients 8 years of age and older who have received no pr
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 191. Rosa Canina Whole (T-37) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=53f30df6-b135-4d17-b747-b95619873474
- doc_id: `openfda_labels:53f30df6-b135-4d17-b747-b95619873474` | sections: 7
- automated checks: all pass
- first 300 characters: Resignation, apathy. Resignation, apathy. INGREDIENTS ACTIVE Rosa Canina 6/8/30x INACTIVE 20% alcohol in purified water. SUGGESTED DOSAGE One dropper under tongue two times daily. Acute symptoms ½ dropper under tongue every 30 minutes for two hours. Use only if cap seal is unbroken. If pregnant or b
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 192. Serotonin/L-Tryptophan (Serotonin/L-Tryptophan 1548) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=bf061e0e-119c-405f-bdbe-b016beff768d
- doc_id: `openfda_labels:bf061e0e-119c-405f-bdbe-b016beff768d` | sections: 7
- automated checks: all pass
- first 300 characters: For the temporary relief of sleep disturbance, bloating, constipation, skin inflammation, or insomnia due to sensitivity to phenolic compounds found in foods or other products.\* \*Claims based on traditional homeopathic practice, not accepted medical evidence. Not FDA evaluated. ACTIVE INGREDIENTS 
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 193. Solifenacin Succinate - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=aea71cde-6d62-4f8d-b813-47064cb213d9
- doc_id: `openfda_labels:aea71cde-6d62-4f8d-b813-47064cb213d9` | sections: 15
- automated checks: all pass
- first 300 characters: Solifenacin succinate tablet is a muscarinic antagonist indicated for the treatment of overactive bladder with symptoms of urge urinary incontinence, urgency, and urinary frequency. Solifenacin succinate tablets are muscarinic antagonist indicated for the treatment of overactive bladder with symptom
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 194. Sophora Alopecuroides L (V-Fresh Restore Gel) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=57b82e44-0169-8577-e063-6294a90ad1a9
- doc_id: `openfda_labels:57b82e44-0169-8577-e063-6294a90ad1a9` | sections: 10
- automated checks: all pass
- first 300 characters: Helps moisturize and maintain vaginal dryness Helps soothe and provide long-lasting comfort Supports intimate microbiome balance Helps maintain a healthy vaginal environment Botanical Care SOPHORA ALOPECUROIDES L 20% Remove one tube from the package. Gently insert one tube into the vagina at bedtime
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 195. Tenofovir Alafenamide (Vemlidy) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=72e6b33c-0351-4070-9172-eeaa186c01d2
- doc_id: `openfda_labels:72e6b33c-0351-4070-9172-eeaa186c01d2` | sections: 15
- automated checks: all pass
- first 300 characters: POSTTREATMENT SEVERE ACUTE EXACERBATION OF HEPATITIS B Discontinuation of anti-hepatitis B therapy, including VEMLIDY, may result in severe acute exacerbations of hepatitis B. Hepatic function should be monitored closely with both clinical and laboratory follow-up for at least several months in pati
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 196. Trimethobenzamide Hydrochloride (Tigan) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=00ba5395-1455-4ea9-9278-e3749979526c
- doc_id: `openfda_labels:00ba5395-1455-4ea9-9278-e3749979526c` | sections: 12
- automated checks: all pass
- first 300 characters: Trimethobenzamide hydrochloride capsules is indicated in adults for the treatment of postoperative nausea and vomiting and for nausea associated with gastroenteritis. Limitation of Use: Trimethobenzamide hydrochloride capsules is not recommended for use in pediatric patients due to the risk of extra
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 197. Xanomeline And Trospium Chloride (Cobenfy) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=8f0e73bf-6025-44f6-ab64-0983322de0df
- doc_id: `openfda_labels:8f0e73bf-6025-44f6-ab64-0983322de0df` | sections: 14
- automated checks: all pass
- first 300 characters: COBENFY is indicated for the treatment of schizophrenia in adults. COBENFY is a combination of xanomeline, a muscarinic agonist, and trospium chloride, a muscarinic antagonist, indicated for the treatment of schizophrenia in adults. ( 1 ) • Assess liver enzymes and bilirubin prior to initiating trea
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 198. Umeclidinium Bromide And Vilanterol Trifenatate (Anoro Ellipta) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=2dbd0671-c565-40c5-bf0f-e324db26799c
- doc_id: `openfda_labels:2dbd0671-c565-40c5-bf0f-e324db26799c` | sections: 15
- automated checks: all pass
- first 300 characters: ANORO ELLIPTA is indicated for the maintenance treatment of patients with chronic obstructive pulmonary disease (COPD). Limitations of Use ANORO ELLIPTA is NOT indicated for the relief of acute bronchospasm or for the treatment of asthma. The safety and effectiveness of ANORO ELLIPTA in asthma have 
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 199. Vestronidase Alfa (Mepsevii) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=925d4e21-fd98-474d-a34d-a0b3558ed750
- doc_id: `openfda_labels:925d4e21-fd98-474d-a34d-a0b3558ed750` | sections: 12
- automated checks: all pass
- first 300 characters: ANAPHYLAXIS Anaphylaxis has occurred with MEPSEVII administration, as early as the first dose \[see Warnings and Precautions ( 5.1 )\] , therefore appropriate medical support should be readily available when MEPSEVII is administered. Closely observe patients during and for 60 minutes after MEPSEVII 
- [ ] auditor: clean / [ ] not clean (reason: ...)

## 200. 100% White Petrolatum (ProCure Petroleum) - US drug label

- source: `openfda_labels` | language: `en` | audience: `patient` | licence: `CC0-1.0` | reuse: `paraphrase_ok`
- URL: https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=3eddf0e7-8e9d-a311-e063-6394a90ad156
- doc_id: `openfda_labels:3eddf0e7-8e9d-a311-e063-6394a90ad156` | sections: 9
- automated checks: all pass
- first 300 characters: Temporarily protects minor: cuts, scrapes, burns Temporarily protects chafed, chapped or cracked skin Helps protect against the drying effects of wind and cold weather Helps treat and prevent diaper rash. Protects chafed skin due to diaper rash and helps seal out wetness Skin Protectant Active Ingre
- [ ] auditor: clean / [ ] not clean (reason: ...)

