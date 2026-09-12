# Data connections

SurveyHQ can ingest the same analysis-ready dataset layer from several collection systems. A connection owns the server address, encrypted credential, project destination, selected resources and automatic refresh schedule. Once imported, data from every provider behaves like any other SurveyHQ dataset: it can feed analysis, dashboards, indicators, fieldwork monitoring and data-quality rules.

## Supported sources

| Source | What SurveyHQ discovers | Import representation |
| --- | --- | --- |
| **Survey Solutions** | Questionnaires and versions | Native Stata/tab/SPSS export ZIP, one dataset per roster level plus paradata |
| **ODK Central** | Projects and forms | Central CSV ZIP, preserving repeat tables as separate datasets |
| **KoboToolbox** | Survey assets through KPI v2 | Submission JSON flattened to CSV; nested/repeat values are retained as JSON cells |
| **SurveyCTO** | Server forms | Wide CSV export |
| **CSPro / CSWeb** | CSPro dictionaries | Case JSON flattened to CSV |
| **SDMX REST API** | Data queries configured on the connection | SDMX-CSV returned by the provider |

The first five are survey/census collection systems commonly encountered in official-statistics work. SDMX is different: it is a statistical exchange/dissemination standard, so SurveyHQ treats it as an additional data-source provider rather than as a questionnaire platform.

## Creating a connection

Open **Connections → Add connection**, choose the provider, enter its server URL and credentials, and select the SurveyHQ project that should receive imported datasets. Save the connection first, then reopen it to discover and select the forms/resources that automatic imports should refresh.

Secrets are stored in the existing encrypted credential field and are never returned by the API. All provider HTTP clients use SurveyHQ's outbound network guard, including redirect checks, so a connection cannot be used to reach loopback, link-local/cloud-metadata or otherwise non-routable addresses.

### Survey Solutions

Use the Headquarters site root, workspace, API user and password. SurveyHQ keeps its existing questionnaire-version behavior: choosing a questionnaire can include future published versions, and several versions are combined into the same roster datasets with `questionnaire_version` provenance.

### ODK Central

Use the Central server root and a Central web-user account. An optional **ODK project id** limits discovery to one project; leaving it blank discovers forms in every project available to that account. SurveyHQ downloads Central's `submissions.csv.zip`, so repeat groups remain separate tables rather than being discarded.

### KoboToolbox

Use the Kobo server root and an API token. SurveyHQ uses the KPI v2 assets and data APIs. Top-level submission columns become normal columns; nested objects and repeat arrays are serialized as JSON in their cells so information is not silently lost. A later connector version can promote repeat groups to child datasets where an installation needs relational Kobo exports.

### SurveyCTO

Use the SurveyCTO server root and API username/password. SurveyHQ discovers forms and imports the wide CSV representation. Imports are executed serially by the connection worker rather than fanning out parallel full-data requests.

### CSPro / CSWeb

Use the CSWeb installation root such as `https://stats.example.org/csweb`. SurveyHQ works against the CSWeb `/api` service, discovers dictionaries, and imports their cases. The connection credential is the CSWeb user account used for synchronization.

### SDMX REST

SDMX services vary in the dataflows they publish and the precise version of the REST standard they expose, so the connection records explicit **data query paths** rather than guessing a provider-specific catalogue. Enter one relative path per line:

```text
Population | data/DF_POP/.?startPeriod=2020
Labour force | data/DF_LFS/..A?startPeriod=2024
```

The text before `|` is the friendly name; the text after it is requested relative to the configured SDMX API root. SurveyHQ asks for SDMX-CSV. The data query therefore needs to support a CSV representation. Public SDMX services can be used without credentials; username/password may be supplied for protected services.

## Refresh semantics

**Replace** is the normal monitoring mode. The dataset row keeps the same SurveyHQ id while its Parquet data is replaced, so dashboards, indicators, relationships and quality rules continue to point at the refreshed dataset.

**Append** is for genuinely incremental feeds. SurveyHQ appends only when the source really contains new rows; appending cumulative exports will duplicate observations.

Automatic refresh supports either an elapsed interval or named times of day in the fieldwork timezone. The same scheduler handles all providers.

## Provenance

Datasets imported from non-Survey-Solutions connections have source `external`, retain the connection id and a stable resource identity, and receive a provider tag such as `odk-central` or `sdmx`. Re-imports match on connection + resource + project, so two projects or two collection servers can carry identically named forms without being mixed together.
