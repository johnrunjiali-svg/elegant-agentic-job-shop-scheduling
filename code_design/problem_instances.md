# Data of Problem Instances

`jsonl` format, each line is a job.

job: due time, value, operations

machines: a json file, defines the machine that is avaliable

create the data, so that, there are inherently bottle neck machines.

```jsonl
{"job_id": "J001", "name": "EngineBlock", "due_time": "2026-03-27T17:00:00-07:00", "reward": 500, "operations": [{"op_id": "O001", "name": "Drilling", "machines": ["M2"], "processing_time": 30}, {"op_id": "O002", "name": "Milling", "machines": ["M3"], "processing_time": 45}, {"op_id": "O003", "name": "Grinding", "machines": ["M4"], "processing_time": 20}]}
{"job_id": "J002", "name": "GearShaft", "due_time": "2026-03-28T12:00:00-07:00", "reward": 300, "operations": [{"op_id": "O201", "name": "Turning", "machines": ["M1"], "processing_time": 25}, {"op_id": "O202", "name": "Grinding", "machines": ["M4"], "processing_time": 15}]}
```

```jsonl
{"group_id": "MG001", "name": "M1", "description": "CNC Drilling Station", "machines": [{"machine_id": "M1-A", "name": "CNC Drill Alpha"}, {"machine_id": "M1-B", "name": "CNC Drill Beta"}, {"machine_id": "M1-C", "name": "CNC Drill Gamma"}]}
{"group_id": "MG002", "name": "M2", "description": "Milling Center", "machines": [{"machine_id": "M2-A", "name": "Mill Alpha"}, {"machine_id": "M2-B", "name": "Mill Beta"}]}
{"group_id": "MG003", "name": "M3", "description": "Turning Center", "machines": [{"machine_id": "M3-A", "name": "Lathe Alpha"}]}
{"group_id": "MG004", "name": "M4", "description": "Grinding Station", "machines": [{"machine_id": "M4-A", "name": "Grinder Alpha"}, {"machine_id": "M4-B", "name": "Grinder Beta"}]}
```
