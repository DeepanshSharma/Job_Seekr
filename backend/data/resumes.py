# Resume content summaries used by the routing LLM.
# Full text versions are stored in Supabase after upload.

DA_RESUME = """
Name: Deepansh Sharma
Role Focus: Data Analyst

Summary: Data Analyst with hands-on experience building data pipelines, dashboards,
and self-service analytics using SQL, Python, and Power BI. Strong focus on data
cleaning, validation, KPI tracking, and data quality.

Key Skills: SQL, Python, Power BI, Tableau, Excel (Pivot Tables, Power Query),
MySQL, DB2, AWS, Git, Informatica MDM.

Experience Highlights:
- Data & Analytics Engineer at American Witness: spatial analytics dashboards,
  heatmaps, Python/SQL ingestion pipelines, REST API integrations.
- Data Analyst at Alstom: Power BI dashboards for work orders/KPIs, automated
  reporting with Python/VBScript, reduced reporting cycle time by 50%.
- Software Engineer at TCS: MDM systems, batch workflow monitoring, SQL-based
  data quality investigation.

Education: MS Computer Science, George Washington University, GPA 3.6
"""

BA_RESUME = """
Name: Deepansh Sharma
Role Focus: Business Analyst

Summary: Business Analyst with experience translating business questions into
data-driven insights, gathering stakeholder requirements, and building reporting
frameworks that drive operational decisions.

Key Skills: Requirements gathering, KPI definition, SQL, Power BI, Excel,
process documentation, cross-functional collaboration, data governance.

Experience Highlights:
- Data & Analytics Engineer at American Witness: integrated AI automation tools
  into editorial workflows, reduced research turnaround by 80%, minimized ad hoc
  data requests through self-service analytics.
- Data Analyst at Alstom: partnered with engineering teams to define KPIs, document
  processes, and introduce the first centralized dashboard used company-wide.
- Software Engineer at TCS: collaborated with business users and data governance
  teams to gather reporting requirements and implement SQL/Power BI enhancements.

Education: MS Computer Science, George Washington University, GPA 3.6
"""

AI_RESUME = """
Name: Deepansh Sharma
Role Focus: Data Scientist / AI Engineer

Summary: Early-career Data Scientist with ML project experience, Python-based
pipeline development, and exposure to LLM-powered automation in production settings.

Key Skills: Python, scikit-learn, TensorFlow, Keras, pandas, SQL,
PCA, cross-validation, LLM integration (Gemini, Groq), LangChain basics,
REST APIs, FastAPI.

Experience Highlights:
- Data & Analytics Engineer at American Witness: integrated LLM-powered document
  summarization and natural language SQL querying into production editorial workflows.
- Cancer Drug Sensitivity Prediction: supervised ML pipeline on 26K+ gene expression
  features, PCA dimensionality reduction, TF/Keras models, cross-validation tuning.
- Job_Seekr (personal project): building an AI-driven job application pipeline using
  FastAPI, LangChain, Gemini and Groq APIs for multi-step LLM orchestration.

Education: MS Computer Science, George Washington University, GPA 3.6
  Coursework: Machine Learning, Data Analytics, System Architecture
"""

RESUMES = {
    "DA": DA_RESUME,
    "BA": BA_RESUME,
    "AI": AI_RESUME,
}
