# Elegant Agentic Job Shop Scheduling

> Key Assumption / Observation

排程的好坏与可行性，主要是由**瓶颈**决定的。

> Flexbile Job Shop Scheduling Problem With Job Due Time

Job: consists of a sequence of operations, has a value, and a due time. If finished all operations before due time, recieve full value. Else recieve nothing.

Operation: Can be done on a set of machines, takes some processing time.

> Rolling Horizon Optimization

We can use solver for this problem, however, the problem could be large, consists of hundreds of job, and thousands of operations. One natural (?) way for dealing with this is dividing problems into solvable sub windows. 

This is what we called rolling horizon optimization (RHO). To perform RHO, we first need a heuristic, to give us a ordering of jobs. We choose job to be basic scheduling unit, because our objective is to maximize the total amount of value we recieve, which is determine by the end time of the last operation, hence we need the whole job inside window. 

The first heuristic comes to my mind for ordering jobs, would be, a heuristc that together consider the job's due time, the time it need, and its value. 

Then, it is the rolling part. For the first $M$ jobs, we call solver on it, and get start and end time assignment for each of them. Then, we fixed the start and end time for the first $K$ jobs, and form the next window consists of job $K+1, ..., K+M$.

A trick here is that, when solving the next window given fixed previous jobs, we don't need to consider the space of the previous jobs, but just say the start time of current window jobs must later than the end time of all previous fixed jobs. This may produce sub optimal schedule, but as long as our windows are overlapping for a reasonable proportion, this should not be a big problem.

Oh to be clear, when determine which job to be fixed, we use the end time of jobs, and select the first $K$. If later jobs has operations before fixed job's operation, we also can fixed those operation.

Since it is the number of operations mainly influnce the solver's performence, we can dynamically selecting window size, based on number of operations for the unschedule jobs.

> Bottleneck Machines

This is the key observation (assumption) of this project, we conject that, only several machines would be very busy, while others with redundent capacity. Hence, we only need to do scheduling on those bottle neck machines. This reduce the complexity of the problem, and hence we can call solver with larger window size, hence better resutls.

## Agentic Scheduling: What Tools Should We Provide?

> Heuristic for Determine Orderings of Jobs

A heuristic function, given set of machines, and weights over them,  set of jobs, and respectively start and end time on each machine, return the ordering of jobs. 

> Solver on a Window

An OR-Tools sovler, given set of machines, set of jobs, and respectively start and end time on each machine, return the scheduled start and end time for each operation. If an operation's machine isn't find inside the set of machines given to the solver, then it means that, we assume that we have redundant enough capacity on that machines.

The agent can choose how to form the window, which machines taken into account, and which machines viewing as having redundant capacity. The agent also choose what jobs to taken into consider in that window, this can be done by calling the heuristic function.

> Post Processing

After calling the solver, for jobs and their operations, we assign the machine and start and end time for operations who works on the bottleneck machines, and start and end time only for other operations. We need post processing to assign machines to these operations. How do we do that? We just use the start time as ordering of operations, and put them in one by one (we now limit ourself to case, where we have the concept of machine groups, so basically job shop scheduling with machine capacity larger than one). For real flexible job shop scheduling, we will need more complex methods to resolve conflict.

> Bottle Neck Anaylsis Tool

This is the most important tool we provide to the agent. Post processing can be viewed as part of it. It identify the bottle neck machines, give feedbaks. Why sayig post processing is part of it? Well, another important feeback, is how many conflicts we resolve, on each machine group. If the number of conflicts is high, that means, we actually should treat that machine as a bottle neck. Anyway, the aim of this tool, is to provide valuable information about bottle neck, can consists of values like 设备利用率，订单按时交付率.

One interesting direction is, some times, we won't be able to finished all jobs on time. We have to give up some jobs, and it should be the agent's job (or other tools' job), to determine what jobs to do, and what jobs to give up.

We can think of all kinds of ideas about how to design this bottle neck analysis tool. For instance, we can slightly modify the start and end time on some machines, and then, we see how much conflicts we will need to solve on other machines, the more conflicts we need to solve, the more bottle neck it is. Many many ways to do so.


