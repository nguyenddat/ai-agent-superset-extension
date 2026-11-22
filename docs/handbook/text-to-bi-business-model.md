# Business model management

**Implemented:** the Text to BI backend stores data layers, business domains, dataset to layer assignments, and a per database business canvas in Superset metadata. It uses Superset database IDs and dataset IDs. Business domains may be associated to existing dataset dictionary rows. The business model module owns these records; the data dictionary owns dictionary metadata and `data_lineage` owns lineage canvases and edges.

The data layer model stores a unique name, description, color, hierarchical level, and sort order. Domain records store a name, description, color, and dataset membership. Canvas layout is persisted as JSON text keyed by Superset database.

This module keeps layer assignments in its own `dataset_layers` table so it does not add a column to the data dictionary model. Lineage APIs and lineage canvas/edge records remain in the data lineage module.
