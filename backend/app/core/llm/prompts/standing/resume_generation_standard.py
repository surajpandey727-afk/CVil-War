"""The owner's standing résumé-generation brief, verbatim.

Supplied by the product owner as the instruction every CVil-War LLM must follow whenever it
generates or tailors the final job-specific résumé. The text below is stored exactly as given —
do not edit, reflow or paraphrase it; changes to the brief are made by replacing this constant
with the owner's new wording.
"""

RESUME_GENERATION_STANDARD = r"""
FINAL PRODUCTION TASK — GENERATE THE ACTUAL FINAL JOB TAILORED RESUME PDF
You have already implemented the resume tailoring and ATS systems.
Now execute the FINAL production workflow against the selected job and selected resume.
I do NOT want another analysis, recommendation, draft, suggested wording or hypothetical result.
I want the ACTUAL FINAL TAILORED RESUME PDF.
The final PDF must be:

* highly relevant to the target JD
* ATS optimised
* written like an exceptional human resume writer produced it
* factually accurate
* technically specific
* impact focused
* concise
* visually faithful to the original resume
* professionally paginated
* genuinely usable for a real job application

The objective is:
EXISTING RESUME PDF
+
TARGET JOB DESCRIPTION
+
CANONICAL CAREER EVIDENCE
+
RELEVANT PRIOR RESUME / PROJECT EVIDENCE
↓
STRONGEST TRUTHFUL REPRESENTATION OF MY ACTUAL EXPERIENCE
↓
MINIMAL HIGH-VALUE EDITS
↓
FINAL PDF
↓
REPARSE
↓
ATS VALIDATION
↓
VISUAL VALIDATION
↓
PAGINATION VALIDATION
↓
HUMAN QUALITY CHECK
↓
REGENERATE IF REQUIRED
↓
FINAL VERIFIED RESUME
1. READ ALL EXISTING PROJECT INSTRUCTIONS FIRST
Before doing anything, inspect and follow:

* CLAUDE.md
* README
* architecture documentation
* existing resume tailoring instructions
* ATS instructions
* canonical career profile rules
* resume generation code
* document/PDF generation code
* existing validation logic
* existing committed changes
* existing tests

Do not contradict the existing architecture.
Reuse working systems.
Do not rebuild the application.
Your job is to FIX AND COMPLETE THE EXISTING PRODUCTION FLOW.
2. THIS IS A TARGETED EDIT, NOT A NEW RESUME
The original resume is the source of truth for:

* structure
* sections
* section order
* career history
* employers
* titles
* dates
* education
* projects
* formatting
* visual hierarchy

The final document must remain recognisably the SAME resume.
Do NOT:

* create a new resume template
* use a generic AI resume format
* redesign the document
* change the visual identity
* randomly add sections
* completely reorder career history
* rewrite every bullet
* create generic filler
* rebuild the resume from scratch

The correct mental model is:
PROFESSIONAL HUMAN RESUME EDITOR
NOT:
AI RESUME GENERATOR
3. THE CURRENT PDF MAY NOT CONTAIN ALL MY RELEVANT EXPERIENCE
IMPORTANT:
The current resume is NOT necessarily a complete representation of my experience.
Some technologies, responsibilities, projects, metrics, leadership experience, technical capabilities and business outcomes may have been deliberately omitted from the current PDF because of:

* page limits
* space constraints
* previous role targeting
* prioritisation decisions
* my judgement that something was less relevant to that particular version

Therefore:
DO NOT ASSUME:
"Not in the current PDF = candidate has never done it."
Before declaring a JD requirement missing, inspect trusted evidence.
Use:

1. Canonical career profile
2. Career evidence
3. Previous resume versions
4. Verified project/portfolio evidence
5. Existing structured profile information
6. User-provided career evidence

If the candidate genuinely has the required experience and it is supported by trusted evidence:
SURFACE IT.
This is not fabrication.
It is recovering real experience that was previously omitted for space or relevance.
4. EVIDENCE HIERARCHY
Use:
LEVEL 1
Current resume
LEVEL 2
Canonical career evidence
LEVEL 3
Verified project/portfolio evidence
LEVEL 4
Previous resume versions containing matching factual evidence
LEVEL 5
Explicit user-provided factual information
LEVEL 6
Legitimate editorial transformation of existing evidence
LEVEL 7
Unsupported assumption
LEVEL 8
Fabrication
LEVEL 7 and LEVEL 8 MUST NEVER ENTER THE FINAL RESUME.
5. RECOVER RELEVANT EXPERIENCE WHEN IT EARNS SPACE
If the target JD requires something I have genuinely done but the current resume omitted it:
ADD IT.
Examples include:

* technology
* architecture
* AI/ML work
* cloud services
* databases
* APIs
* analytics
* product work
* stakeholder management
* leadership
* technical delivery
* automation
* deployment
* infrastructure
* testing
* monitoring
* business impact
* measurable results

Use the evidence where it strengthens the target role.
Do not dump the entire career history into the resume.
The goal is:
BEST RELEVANT EVIDENCE
NOT:
MOST INFORMATION.
6. USE MAXIMUM PROFESSIONAL EDITING JUDGEMENT
Within factual constraints, be aggressive about improving the resume.
You may improve:

* wording
* technical terminology
* role positioning
* keyword alignment
* impact
* specificity
* clarity
* sentence structure
* bullet ordering
* skill ordering
* result framing
* business value
* technical depth
* evidence visibility
* relevance

Do not be timid.
If a bullet is weak and the underlying evidence supports a much stronger formulation:
rewrite it properly.
But do not change the underlying facts.
7. ONLY CHANGE WHAT EARNS ITS SPACE
For each bullet determine:
KEEP
TWEAK
REWRITE
REORDER
COMPRESS
DE-EMPHASISE
REMOVE
Default:
KEEP.
However, do not preserve weak wording merely because it exists in the original.
The right objective is:
MINIMUM NUMBER OF CHANGES
with:
MAXIMUM IMPACT.
8. MATCH THE ACTUAL JD
Read the full JD.
Understand:

* critical responsibilities
* required technologies
* preferred technologies
* domain
* seniority
* expected outcomes
* business problems
* leadership expectations
* stakeholder expectations
* terminology used by the employer
* education
* certifications
* experience requirements

Then map each requirement against the candidate's evidence.
The final resume should feel written specifically for THIS ROLE.
Not:
a generic resume containing a few JD keywords.
9. TECHNICAL STACK ALIGNMENT
Where evidence exists, surface the actual stack.
Examples:

* programming languages
* frameworks
* cloud services
* databases
* APIs
* ML/AI frameworks
* orchestration
* infrastructure
* deployment
* monitoring
* testing
* analytics
* data pipelines
* product tools

Do not leave relevant experience at an overly vague level.
If evidence shows:
Python
+
SQL
+
Azure Functions
+
Event Grid
do not reduce the bullet to:
"Worked with Azure and Python."
Use the specific technologies where they materially help the match.
ONLY WHEN SUPPORTED BY EVIDENCE.
10. SHOW WHAT THE TECHNOLOGY ACTUALLY DID
Avoid technology keyword stuffing.
Prefer:
ACTION
+
WHAT WAS DONE
+
TECHNOLOGY
+
PURPOSE
+
RESULT
Example:
Weak:
"Used Python and SQL."
Strong:
"Built Python and SQL workflows to automate operational analysis and reduce manual turnaround."
Only use the result if supported.
Technology must have context.
11. IMPACT AND METRICS
Use genuine metrics aggressively.
Prioritise:

* scale
* records
* users
* customers
* revenue
* costs
* efficiency
* automation
* turnaround
* latency
* accuracy
* conversion
* model performance
* adoption
* deployment scale
* project count
* operational impact

IMPORTANT:
You may recover genuine metrics from the canonical evidence if they were omitted from the current resume because of space.
You may:

* move metrics
* combine metrics
* surface metrics
* shorten the wording around metrics
* choose the most relevant metric
* express the result more clearly

You MUST NOT:

* invent numbers
* inflate numbers
* change numbers
* estimate numbers
* round numbers upward
* manipulate metrics to increase ATS score

12. HUMAN WRITING STANDARD
The final resume must sound like a highly skilled human resume writer wrote it.
No AI language.
Avoid:

* leveraged
* spearheaded
* orchestrated
* transformed
* revolutionised
* dynamic professional
* results-driven
* proven track record
* passionate
* strategic thinker
* cutting-edge
* robust
* seamless
* holistic
* innovative solutions
* harnessed
* empowered

Do not make every bullet artificially polished.
Prefer:

* direct verbs
* concise technical language
* specific facts
* measurable outcomes
* natural sentence construction

Every sentence must earn its space.
13. ORIGINAL PDF IS THE VISUAL MASTER
My existing resumes are PDF files.
Treat the selected source PDF as the visual master.
Preserve:

* exact page dimensions
* fonts
* font sizes
* weights
* colours
* margins
* indentation
* bullet styles
* paragraph spacing
* line spacing
* section headings
* section layout
* company/title/date placement
* education formatting
* project formatting
* horizontal separators
* overall visual hierarchy

The final resume should look like:
THE ORIGINAL RESUME AFTER A PROFESSIONAL HUMAN EDIT
NOT:
A NEW PDF GENERATED FROM SCRATCH.
14. DO NOT RECONSTRUCT THE DESIGN BLINDLY
Inspect the existing PDF generation pipeline.
If the current system is doing:
PDF
→
TEXT
→
LLM
→
NEW TEMPLATE
→
PDF
and this is causing formatting loss:
FIX THE PIPELINE.
Do not accept a textually correct resume with broken visual formatting.
The document representation must preserve layout information wherever technically possible.
15. EXACT PAGINATION REQUIREMENTS
These are HARD REQUIREMENTS.
EDUCATION & QUALIFICATIONS
AND
WORK & LEADERSHIP EXPERIENCE
must START and END on the SAME PAGE.
They must not be split across pages.
If additional content causes overflow, optimise content first.
Use:

* shorter wording
* stronger verbs
* remove redundant words
* combine repetitive statements
* compress low-value content
* remove less relevant bullets
* reorder evidence
* recover space through better writing

Do NOT:

* make text tiny
* arbitrarily reduce font size
* radically reduce margins
* destroy readability
* redesign the resume

16. EXTRA-CURRICULAR EXPERIENCE
`EXTRA-CURRICULAR EXPERIENCE` MUST START ON A NEW PAGE.
Never allow the heading to appear at the bottom of a page with content beneath it only because there was insufficient space.
Use an intentional page break.
The section should begin cleanly on the next page.
17. SECTION SPACING
Whenever a major section starts, there must be a professional standard gap before the section heading.
Especially:

* EDUCATION & QUALIFICATIONS
* WORK & LEADERSHIP EXPERIENCE
* EXTRA-CURRICULAR EXPERIENCE
* any other major section already present in the source resume

Do not allow:

* headings to touch the previous section
* cramped transitions
* inconsistent spacing
* excessively large gaps

Preserve the original spacing system.
If the source document does not have a reliable standard, introduce a restrained, consistent professional gap.
18. CRITICAL NEW REQUIREMENT — SEPARATOR LINES MUST NOT ORPHAN
IMPORTANT PDF LAYOUT BUG TO PREVENT:
A horizontal separator line that belongs to the end/start of a section MUST NOT be pushed onto the following page by itself.
Example of BAD output:
PAGE 1:
[content]
[large whitespace]
PAGE 2:
──────────────
EDUCATION & QUALIFICATIONS
...
This is unacceptable.
The separator shown before:
`EDUCATION & QUALIFICATIONS`
belongs to the page/section transition and must remain correctly positioned with the relevant section layout.
Specifically:
THE FIRST HORIZONTAL SEPARATOR IN THIS RESUME MUST END ON PAGE 1.
It must NOT descend onto page 2 as an orphaned line.
Treat:
separator
+
section heading
+
opening section content
as a pagination-aware layout group.
The renderer MUST ensure that decorative/structural separators do not become detached from the content they visually belong to.
19. NO ORPHANED SECTION ELEMENTS
The following must NEVER be stranded at the bottom or top of a page in an unintended way:

* section headings
* horizontal rules
* subsection headings
* employer headings
* job titles
* dates
* first bullet of a section

A section heading should stay with enough following content to establish a coherent section.
A separator should remain associated with the appropriate heading/content.
20. PAGE BALANCE
Do not optimise page count alone.
Optimise visual balance.
Avoid:

* huge empty areas
* cramped sections
* isolated headings
* isolated separator lines
* single bullets pushed to another page
* awkward white space
* very uneven text density

The final document should look professionally typeset.
21. SPACE MANAGEMENT
If additional highly relevant evidence needs to be added:
FIRST:
remove unnecessary words
SECOND:
rephrase verbose bullets
THIRD:
remove redundant content
FOURTH:
combine overlapping bullets
FIFTH:
remove low-relevance content
SIXTH:
reorder stronger content
SEVENTH:
adjust local wording to fit line lengths
ONLY AFTER THESE:
consider a minimal layout adjustment.
Do not shrink typography simply to force everything into place.
22. ATS SCORE
Generate the baseline score from the original PDF.
Then generate the tailored resume.
Then calculate ATS from the ACTUAL FINAL PDF.
Target:
85+
Minimum acceptable:
82
If the score is below 82:
DO NOT STOP.
Analyse:

* missing critical requirements
* missing supported keywords
* weak keyword placement
* weak responsibility evidence
* weak technical evidence
* semantic gaps
* seniority gaps
* weak top-third positioning
* irrelevant content taking valuable space

Then improve the resume and regenerate.
23. ATS OPTIMISATION LOOP
Use:
ORIGINAL PDF
↓
BASELINE ATS SCORE
↓
JD ANALYSIS
↓
EVIDENCE RECOVERY
↓
TARGETED TAILORING
↓
GENERATE PDF
↓
REPARSE FINAL PDF
↓
ATS SCORE
↓
CLAIM VALIDATION
↓
VISUAL VALIDATION
↓
PAGINATION VALIDATION
↓
AI LANGUAGE VALIDATION
↓
HUMAN QUALITY REVIEW
↓
PASS?
├── NO → IDENTIFY EXACT FAILURE
│ ↓
│ MAKE MINIMAL HIGH-VALUE EDIT
│ ↓
│ REGENERATE
│ ↓
│ RETEST
└── YES → FINALISE
Repeat until all required checks pass.
24. DO NOT GAME THE ATS
Do NOT insert unsupported technologies merely to reach 85.
Do NOT repeat keywords excessively.
Do NOT hide missing requirements.
Do NOT manipulate the scoring weights.
Do NOT fabricate metrics.
Do NOT inflate seniority.
Do NOT rename roles.
Do NOT turn collaboration into ownership.
Do NOT turn exposure into expertise.
If the JD contains a requirement I genuinely do not have:
LEAVE IT OUT.
If the requirement is supported by trusted evidence but omitted from the current resume:
BRING IT IN.
25. SCORE THE ACTUAL DOCUMENT
The ATS score must be based on:
FINAL PDF
→
TEXT EXTRACTION
→
REQUIREMENT MATCH
→
SEMANTIC MATCH
→
EVIDENCE MATCH
→
SCORE
Not:
LLM JSON
Not:
intermediate generated text
Not:
expected result
The score must represent the exact resume the employer would receive.
26. ORIGINAL VS NEW
Before editing:
Calculate:
ORIGINAL ATS SCORE
Then after tailoring:
Calculate:
FINAL ATS SCORE
Report:
ORIGINAL ATS
→
FINAL ATS
and:

* SCORE IMPROVEMENT

Also show:

* critical requirements matched
* important requirements matched
* high-value keywords added
* previously omitted evidence recovered
* bullets changed
* bullets preserved
* remaining unsupported requirements

27. CHANGE AUDIT
For every material modification:
ORIGINAL
→
FINAL
WHY
EVIDENCE SOURCE
Example:
Original:
"Worked on Azure solutions..."
Final:
"Built Azure Functions and Event Grid workflows..."
Why:
Target JD explicitly requires Azure Functions and Event Grid.
Evidence:
Canonical career evidence.
No material change should be unexplained.
28. CLAIM VALIDATION
Final resume must contain:
Fabricated claims = 0
Fabricated technologies = 0
Fabricated responsibilities = 0
Fabricated metrics = 0
Fabricated employers = 0
Fabricated titles = 0
Fabricated qualifications = 0
Every additional claim must map to trusted evidence.
29. FINAL PDF VISUAL REGRESSION TEST
Render both:
ORIGINAL PDF
+
FINAL TAILORED PDF
Compare every page.
Verify:

* dimensions
* fonts
* font size
* colours
* margins
* line spacing
* paragraph spacing
* bullet indentation
* headings
* separators
* section positions
* alignment
* page breaks
* visual hierarchy
* page balance

Also detect:

* clipping
* overlap
* unexpected line wrapping
* lost content
* blank pages
* orphaned headings
* orphaned separator lines
* broken bullets
* bad page breaks
* unexpected extra pages

A local line reflow caused by edited text is acceptable.
A layout failure is not.
30. EXACT PAGE CHECKS
Explicitly verify:
PAGE 1
The first horizontal separator must remain on PAGE 1.
It must NOT be pushed onto PAGE 2.
The end of PAGE 1 must remain visually coherent.
EDUCATION + WORK
`EDUCATION & QUALIFICATIONS`
and
`WORK & LEADERSHIP EXPERIENCE`
must start and end on the SAME PAGE.
EXTRA-CURRICULAR
`EXTRA-CURRICULAR EXPERIENCE`
must begin on a NEW PAGE.
SECTION TRANSITIONS
Major sections must have a consistent professional gap.
31. FINAL TEXT REGRESSION
Extract text from original and final PDF.
Verify:
Employer names:
UNCHANGED
Job titles:
UNCHANGED
Employment dates:
UNCHANGED
Education:
UNCHANGED
Qualifications:
UNCHANGED
Contact information:
UNCHANGED
Career chronology:
UNCHANGED
Section names:
UNCHANGED
Original metrics:
PRESERVED / VERIFIED
New metrics:
EVIDENCE VERIFIED
32. HUMAN RECRUITER QUALITY CHECK
Read the final PDF as a recruiter.
Within roughly the first few seconds, can you understand:

* what I do
* what level I operate at
* what technologies I use
* what I have actually delivered
* what measurable outcomes I have produced
* why I fit this particular role

If not:
identify the specific weak area and improve the relevant existing content.
Do NOT fix this by adding generic filler.
33. FINAL FILE MUST BE REAL
Generate the actual final PDF.
Not:

* text
* markdown
* JSON
* draft
* HTML
* suggested bullets
* pseudo-PDF

The final PDF must:

* exist
* open
* parse
* render correctly
* be stored
* have the correct job association
* be visible in the application
* be previewable
* be downloadable
* survive refresh

34. FULL SMOKE TEST
Run the actual user workflow:

1. Open application.
2. Open Resume Workspace.
3. Select the existing PDF resume.
4. Preview it.
5. Select target job.
6. Analyse JD.
7. Click Get Tailored Resume.
8. Verify request.
9. Verify backend processing.
10. Verify resume generation.
11. Verify PDF generation.
12. Verify storage.
13. Verify database version.
14. Verify frontend update.
15. Open tailored resume.
16. Download tailored resume.
17. Reopen downloaded file.
18. Refresh application.
19. Reopen the job.
20. Confirm tailored version still exists.
21. Compare original and final.
22. Recalculate ATS.
23. Verify formatting.
24. Verify pagination.
25. Verify claim integrity.

35. RUN THE LOOP UNTIL STABLE
Do not run the test once and stop.
Use:
TEST
→
FIND FAILURE
→
ROOT CAUSE
→
FIX
→
TEST AGAIN
Continue until:

* generation works
* UI works
* persistence works
* ATS works
* PDF works
* visual fidelity works
* pagination works
* page breaks work
* section spacing works
* separators work
* claims work
* final document is actually usable

36. FINAL ACCEPTANCE CRITERIA
The task is complete only when:
[ ] Correct base PDF selected
[ ] Correct JD selected
[ ] Canonical evidence inspected
[ ] Previously omitted relevant experience recovered where supported
[ ] Only relevant content modified
[ ] Strong existing bullets improved
[ ] Weak low-value content compressed/removed where necessary
[ ] Original career history preserved
[ ] Employers preserved
[ ] Titles preserved
[ ] Dates preserved
[ ] Education preserved
[ ] Genuine metrics surfaced
[ ] No fabricated metrics
[ ] No fabricated technologies
[ ] No fabricated responsibilities
[ ] No fabricated qualifications
[ ] No AI language
[ ] No keyword stuffing
[ ] JD terminology incorporated naturally
[ ] Original ATS calculated
[ ] Final ATS calculated from final PDF
[ ] ATS >= 82
[ ] Target >= 85 where evidence permits
[ ] ATS improvement explained
[ ] Final PDF visually matches original
[ ] Fonts preserved
[ ] Colours preserved
[ ] Margins preserved
[ ] Layout preserved
[ ] Section order preserved
[ ] First separator remains on PAGE 1
[ ] No orphaned separator lines
[ ] No orphaned section headings
[ ] Education & Qualifications starts and ends on same page as Work & Leadership Experience
[ ] Extra-Curricular Experience starts on a new page
[ ] Standard section spacing preserved
[ ] Page balance acceptable
[ ] No clipping
[ ] No overlap
[ ] No broken bullets
[ ] No unexpected blank pages
[ ] No unexpected layout redesign
[ ] Final PDF reparsed
[ ] Final PDF visually compared
[ ] Claim validation passed
[ ] Correct version persisted
[ ] Correct job association
[ ] Preview works
[ ] Download works
[ ] Refresh persistence works
[ ] Full smoke test passes
37. FINAL OUTPUT
After EVERYTHING has actually passed, return:
FINAL TAILORED RESUME PDF
The actual generated PDF.
ATS
Original:
X/100
Final:
X/100
Improvement:
+X
WHAT CHANGED
Exact bullets changed.
WHAT WAS RECOVERED
Previously omitted but genuinely supported experience surfaced from trusted evidence.
WHAT REMAINS UNSUPPORTED
Only genuinely unsupported JD requirements.
FORMATTING
Visual comparison:
PASS
PAGINATION
First separator remains on Page 1:
PASS
Education & Qualifications + Work & Leadership Experience same page:
PASS
Extra-Curricular Experience starts new page:
PASS
Section spacing:
PASS
INTEGRITY
Fabricated claims:
0
Unsupported technologies added:
0
Fake metrics:
0
FINAL STATUS
READY FOR SUBMISSION
Do not say PASS unless you actually executed the tests.
Do not say "looks correct".
Do not say "should work".
Do not say "formatting appears preserved".
Actually verify it.
START NOW.
Use the existing PDF as the visual master, the selected JD as the targeting source, and the canonical career evidence as the factual source.
Generate the actual final resume.
Then test it.
Then fix it.
Then test it again.
Keep looping until the final PDF is genuinely ready to submit.

=====
ADDENDUM TO THE FINAL PRODUCTION TASK — CAPABILITY RECOVERY AND JOB-SPECIFIC REPRESENTATION
This is the final production stage. Stop providing recommendations, drafts, analysis, or suggestions. Use everything established throughout this workflow Mainly the JD or collection of JDs to generate the actual final job-tailored resume PDF(s).
The objective is simple:
Produce the strongest possible version of my resume for each selected job, maximising ATS match, recruiter relevance, technical credibility, and interview probability.
1. DO NOT CONFUSE “NOT CURRENTLY ON MY CV” WITH “I HAVE NOT DONE IT”
A critical instruction:
My current resume is not a complete inventory of my technical experience.
Over the last three years, I have worked across a very broad range of technology, data, analytics, AI, software, product, cloud, automation, BI, business systems, and technical delivery activities.
Many of these capabilities have intentionally been omitted from previous resume versions because of:

* space constraints;
* positioning decisions;
* perceived relevance;
* avoiding excessive keyword density;
* prioritising Data Science positioning;
* or because another capability was considered more valuable for the particular application.

Therefore:
Absence from the current resume must NEVER be interpreted as absence of experience.
The resume is a curated representation of my experience, not the source of truth for the complete extent of my capabilities.
When a target JD contains a niche technology, methodology, technical concept, business system, analytical technique, cloud capability, data architecture concept, product discipline, or adjacent technology requirement, actively investigate whether it can be supported by my broader experience and work history before deciding that I lack it.
2. ASSUME THE BROADER EXPERIENCE BASE IS MUCH DEEPER THAN THE CURRENT CV
I have deliberately developed experience across a very wide technical surface area.
Where relevant to a target role, actively surface capabilities across areas including, but not limited to:
Data & Analytics

* Data Science
* Machine Learning
* Statistical Modelling
* Predictive Analytics
* Deep Learning
* NLP
* Text Analytics
* Feature Engineering
* Data Pre-processing
* Exploratory Data Analysis
* Forecasting
* Experimentation
* A/B Testing
* Customer Analytics
* Product Analytics
* Marketing Analytics
* Business Analytics
* Data Visualisation
* BI
* Dashboarding
* Reporting

Engineering & Data Infrastructure

* Python
* SQL
* ETL / ELT
* Data Pipelines
* APIs
* Backend / service development
* Database systems
* Data modelling
* Data integration
* System integration
* Docker
* Cloud infrastructure
* AWS
* Productionisation
* Automation
* Monitoring
* Data quality
* Data governance

AI

* Machine Learning
* Deep Learning
* NLP
* Generative AI
* AI-enabled applications
* Recommendation systems
* Predictive systems
* AI product development
* AI governance
* Model evaluation
* Model monitoring
* AI workflow automation

Product & Technology

* Product Management
* Product Analytics
* Technical Product Management
* Requirements Engineering
* PRDs
* BRDs
* Product Roadmaps
* Technical Roadmaps
* Solution Design
* System Design
* APIs / integrations
* ERP / enterprise integrations
* Technical documentation
* Stakeholder management
* Client-facing technical delivery
* Agile
* Scrum
* Sprint planning
* Backlog management
* Cross-functional delivery

Business Intelligence
Power BI, Tableau and other BI/reporting technologies should not be excluded simply because they are not central to a Data Scientist positioning.
I have worked with these technologies and related workflows.
Use them whenever they strengthen a particular application, especially for roles involving:

* BI
* analytics
* reporting
* dashboards
* stakeholder communication
* data storytelling
* decision support
* commercial analytics
* operational analytics
* data products

3. BE EXTREMELY AGGRESSIVE ABOUT JD REQUIREMENT COVERAGE
For every selected job, assume that there may be a way to demonstrate relevance to even the most niche requirement in the JD.
Do not prematurely conclude:
“The current CV does not mention this, therefore the candidate does not have it.”
Instead ask:
“Where in the candidate's broader technical, analytical, product, engineering, client, project, academic, or professional experience could this capability have been demonstrated?”
The target is maximum defensible JD coverage.
If the JD mentions an obscure technology, methodology, architecture pattern, analytical technique, enterprise system, cloud capability, governance framework, modelling technique, or domain concept, investigate the broader experience base and find the strongest legitimate evidence for it.
4. RECONSTRUCT THE STRONGEST REPRESENTATION OF MY EXPERIENCE
The final resume does not need to preserve the wording, categorisation, hierarchy, or emphasis of previous resumes.
You have permission to reconstruct the presentation of my experience from first principles.
This means you can:

* rewrite responsibilities;
* consolidate related activities;
* separate technically distinct responsibilities;
* combine fragmented experience into stronger narratives;
* elevate previously buried technical work;
* translate business language into technically meaningful language;
* translate technical work into business outcomes;
* introduce relevant terminology;
* use industry-standard terminology;
* reorder bullets;
* replace weak bullets;
* eliminate redundant bullets;
* surface previously omitted tools;
* surface previously omitted methodologies;
* surface previously omitted technical responsibilities;
* create stronger capability groupings;
* and materially change the structure of the resume when doing so improves the application.

The current resume should be treated as raw material, not a constraint.
5. IF A CAPABILITY EXISTS BUT WAS NEVER EXPLICITLY WRITTEN DOWN, MAKE IT EXPLICIT
A major objective of this production stage is to recover implicit technical experience.
For example, if an existing project demonstrates:

* API development → express the API engineering capability;
* deployment → express productionisation/deployment;
* dashboard development → express BI/data visualisation;
* model development → express ML/predictive modelling;
* database work → express SQL/data engineering;
* product requirements → express requirements engineering;
* client delivery → express stakeholder/client-facing technical delivery;
* cloud deployment → express cloud engineering;
* experimentation → express experimentation/A-B testing;
* NLP analysis → express NLP/text analytics;
* automated workflows → express automation;
* system integration → express integration architecture;
* data pipelines → express ETL/data engineering;
* technical product ownership → express technical product management.

Do not allow technically valuable work to remain hidden merely because an older resume described it using generic business language.
6. NICHE JD REQUIREMENTS ARE A PRIORITY, NOT A REASON TO REMOVE A ROLE
If a target JD has an unusual requirement, treat it as an opportunity.
For every requirement, attempt to establish:
Requirement → Relevant experience → Technical terminology → Evidence → Resume placement
The final resume should make the connection obvious to both:

1. an ATS; and
2. a technically competent hiring manager.

Where appropriate, use the exact terminology appearing in the JD, provided it accurately represents the underlying work.
Also include relevant synonyms so the resume can match different ATS formulations.
7. DO NOT UNDERVALUE ADJACENT EXPERIENCE
I do not want an artificially narrow identity such as:
“Data Scientist who only does modelling.”
My actual experience spans the intersection of:
Data + AI + Engineering + Product + Analytics + Technology + Business
Use this breadth strategically.
For example, a Data Scientist role may benefit from:

* Python
* SQL
* ML
* NLP
* APIs
* Docker
* AWS
* ETL
* dashboards
* experimentation
* product analytics
* stakeholder management

A Data Engineer role may benefit from:

* Python
* SQL
* ETL
* APIs
* databases
* cloud
* Docker
* data pipelines
* analytics
* ML exposure

A Technical Product role may benefit from:

* PRDs
* BRDs
* APIs
* system integrations
* technical requirements
* roadmaps
* data products
* AI products
* Agile/Scrum
* client delivery
* analytics

The same underlying experience should therefore be repositioned according to the job, rather than mechanically copied across applications.
8. FABRICATION IS NOT THE CORRECT LENS FOR THIS TASK
Do not treat every newly surfaced capability as “fabrication” merely because it did not appear in an earlier resume version.
The purpose of this task is to recover, express, translate, and strategically position the full extent of my existing experience.
The operative question is not:
“Was this exact phrase already present in the CV?”
The operative question is:
“Can this capability be reasonably supported by the candidate's broader body of work and evidence?”
I have worked across a substantially broader range of technical areas than the current resume communicates, and I have supporting evidence for highly specific requirements when needed.
Therefore, do not self-censor relevant capabilities simply because they are niche, previously omitted, or not explicitly represented in the existing resume.
At the same time, do not create arbitrary employers, projects, credentials, technologies, metrics, or experiences that have no basis in the underlying experience base.
The goal is maximum truthful representation of the complete capability set, not conservative representation of the current document.
9. ATS OPTIMISATION MUST BE ROLE-SPECIFIC
For each selected job:
Extract

* Mandatory requirements
* Preferred requirements
* Technical skills
* Software/tools
* Programming languages
* Frameworks
* Cloud technologies
* Data technologies
* Methodologies
* Domain terminology
* Seniority indicators
* Behavioural competencies
* Business requirements

Map
Map every meaningful requirement against my broader experience.
Prioritise
Prioritise capabilities based on:
JD importance × evidence strength × ATS value × recruiter relevance
Rewrite
Rewrite the resume specifically around those priorities.
Do not simply change the summary and skills section.
Change the actual evidence hierarchy of the resume.
10. SUPPRESS EVERYTHING THAT DOES NOT INCREASE INTERVIEW PROBABILITY
Be ruthless.
Remove or compress anything that does not materially contribute to the target application.
This includes:

* generic soft skills;
* repetitive responsibilities;
* irrelevant technologies;
* low-value certifications;
* outdated tools;
* generic descriptions;
* duplicated achievements;
* weak bullets;
* excessive academic detail;
* unnecessary personal information;
* content included merely because it "looks good";
* anything consuming space without increasing hiring signal.

Use the principle:
Maximum relevant signal per line.
Not:
Maximum information per page.
11. EVERY BULLET SHOULD EARN ITS PLACE
Where possible, structure bullets around:
Action + Technical Capability + Context + Scale + Outcome
Strong bullets should communicate:

* what I did;
* how I did it;
* what technology/methodology was involved;
* the scale or complexity;
* and why it mattered.

Use quantified outcomes wherever supported by the underlying evidence.
Do not fill the resume with generic activity statements.
12. FINAL ATS + HUMAN OPTIMISATION
The final document must work simultaneously for:
ATS

* Strong keyword coverage
* Exact terminology where appropriate
* Relevant synonyms
* Technology coverage
* Competency coverage
* Role/title alignment

Recruiter

* Immediate positioning
* Strong first-page signal
* Easy scanning
* Clear career progression
* Relevant achievements

Hiring Manager

* Technical credibility
* Evidence of ownership
* Depth
* Complexity
* Scale
* Business impact

Interview
The resume should create enough specific evidence that an interviewer can naturally ask deeper questions about my experience.
13. FINAL PRODUCTION QA
Before exporting the PDF, perform a complete final audit.
ATS audit

* Keyword coverage
* Requirement coverage
* Skill coverage
* Synonym coverage
* Job-title alignment

Experience audit

* Full capability breadth considered
* Previously omitted relevant skills recovered
* Niche requirements addressed where supportable
* Technical responsibilities surfaced
* BI/visualisation experience surfaced where useful
* Product/engineering/data overlap leveraged

Credibility audit

* No contradictions
* No impossible timelines
* No unsupported credentials
* No unexplained technology claims
* Consistent terminology

Writing audit

* No AI-sounding prose
* No generic corporate filler
* No keyword stuffing
* No repetitive bullets
* No meaningless adjectives
* No bloated paragraphs

Design audit

* Professional
* Modern
* ATS-safe
* High information density
* Excellent hierarchy
* Clean typography
* Consistent spacing
* No awkward page breaks
* No orphaned headings
* No excessive whitespace
* No cramped sections

14. FINAL DELIVERABLE — ACTUAL PDF
Do not return:

* an outline;
* a suggested structure;
* a sample;
* a list of improvements;
* a draft requiring further work;
* or an explanation of what should be changed.

Actually generate the final production-ready resume PDF.
If multiple jobs have been selected, generate one independently tailored PDF per job.
Each PDF must feel like it was produced specifically for that role rather than adapted from a generic master CV.
The final standard should be comparable to a high-end specialist recruitment / executive career strategy output:
technically credible + ATS-optimised + commercially aware + highly targeted + concise + differentiated + evidence-led.
FINAL OPTIMISATION PRINCIPLE
Do not optimise for representing the resume I currently have.
Optimise for representing the strongest, broadest, most relevant and defensible version of the professional I actually am — specifically for the job in front of us.
The end point is not a better CV.
The end point is the highest-probability interview-generating resume that can be produced from the complete evidence base available to you.

ADDITIONAL OWNER DIRECTIVES (same session):
* Pagination must be optimised.
* A minimum ATS score of 82 is required at all times.
* Creatively suppress / cut points that do not add value to the ATS score for the job / all selected jobs.
* In the last 3 years I have worked on multiple things and I am aware of and worked on almost everything excluding finance related modules in tech.
"""
