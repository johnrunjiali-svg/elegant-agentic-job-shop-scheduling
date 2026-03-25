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
> 
