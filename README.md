# Elegant Agentic Job Shop Scheduling

> Key Assumption / Observation

排程的好坏与可行性，主要是由**瓶颈**决定的。

> Flexbile Job Shop Scheduling Problem With Job Due Time

Job: consists of a sequence of operations, has a value, and a due time. If finished all operations before due time, recieve full value. Else recieve nothing.

Operation: Can be done on a set of machines, takes some processing time.

For now, let's assume a job can only works on one machine group.

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

好的，我们现在来写 Solver。这个 Solver 的相关信息你可以在 README 里找到。我先跟你说一下几个关键点：

1. **基本输入与格式**
   *   Solver 会在一个 window（时间窗口）上进行 solve。
   *   输入包括所有machines的情况，以及 jobs 的情况。
   *   你先参考刚才写的 data loader。不管加载出来的是 JSONL 还是其他数据格式，直接在函数里沿用那个格式来处理，保持一致。

2. **时间参数设置**
   *   我们会给所有机器设置 Start Time 和 End Time。
   *   请在代码里设置：Start Time 是必填项（Required），End Time 是选填项（Optional）。如果 End Time 没给，就默认为正无穷。
   *   所有的排程必须落在 [Start Time, End Time] 范围内。如果排不下，程序应该返回一个错误提示，说明时间范围不合法。

3. **机器组与产能约束**
   *   除了所有机器的start time end time详细列表（具体到每一台机器，如 M1-A），我们还会额外传入一组参数，即“需要关注的机器组”列表（例如 M1 组）。
   *   这些被指定的机器组是“瓶颈机组”。我们假设其他未指定的机器组产能是无限的。
   *   **实现细节：**
       *   对于产能无限的机器，你不需要创建变量进行优化。
       *   但是，如果任务中间涉及在这些“无限产能”机器上进行操作，你必须处理好这些 operation 的时长，并把相应的约束加好，确保整个任务的时间链条是完整的。
       *   Solver 的核心工作就是针对给定的瓶颈机组进行排程。

4. **开发建议**
   *   建议使用 OR-Tools 来实现。
   *   你可以直接用 `uv add ortools` 安装环境。
   *   写完后，你可以自己找一些数据测试一下这个 Solver 的逻辑。

你明白我的意思了吧？按这个思路去实现就好。 machines, set of jobs, and respectively start and end time on each machine, return the scheduled start and end time for each operation. If an operation's machine isn't find inside the set of machines given to the solver, then it means that, we assume that we have redundant enough capacity on that machines.

The agent can choose how to form the window, which machines taken into account, and which machines viewing as having redundant capacity. The agent also choose what jobs to taken into consider in that window, this can be done by calling the heuristic function.

> Post Processing

After calling the solver, for jobs and their operations, we assign the machine and start and end time for operations who works on the bottleneck machines, and start and end time only for other operations. We need post processing to assign machines to these operations. How do we do that? We just use the start time as ordering of operations, and put them in one by one (we now limit ourself to case, where we have the concept of machine groups, so basically job shop scheduling with machine capacity larger than one). For real flexible job shop scheduling, we will need more complex methods to resolve conflict.

> Bottle Neck Anaylsis Tool

This is the most important tool we provide to the agent. Post processing can be viewed as part of it. It identify the bottle neck machines, give feedbaks. Why sayig post processing is part of it? Well, another important feeback, is how many conflicts we resolve, on each machine group. If the number of conflicts is high, that means, we actually should treat that machine as a bottle neck. Anyway, the aim of this tool, is to provide valuable information about bottle neck, can consists of values like 设备利用率，订单按时交付率.

One interesting direction is, some times, we won't be able to finished all jobs on time. We have to give up some jobs, and it should be the agent's job (or other tools' job), to determine what jobs to do, and what jobs to give up.

We can think of all kinds of ideas about how to design this bottle neck analysis tool. For instance, we can slightly modify the start and end time on some machines, and then, we see how much conflicts we will need to solve on other machines, the more conflicts we need to solve, the more bottle neck it is. Many many ways to do so.


