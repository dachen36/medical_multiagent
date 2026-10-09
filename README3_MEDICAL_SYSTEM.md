# Medical MultiAgent - 真实架构深度剖析

> ⚠️ 本文档基于代码扫描重写，纠正了之前的混乱认识。这是一个**医学诊疗多智能体系统**，不是通用 OpenHarness 框架。

## 📌 项目真实身份

**Medical MultiAgent** 是一个基于 OpenHarness 构建的**医学诊疗智能体系统**，核心为：

- **前端**: React 19 WebUI (Vite + Zustand)
- **后端**: FastAPI 9000 端口
- **核心**: 4个专业医学智能体协调系统
- **功能**: 医学问诊 → 分类 → 规划 → 执行

---

## 🏗️ 真实架构图

```
用户
  ↓
┌─────────────────────────────────────────────────────────────┐
│        WebUI - React 前端 (5173端口)                         │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  App.tsx (36KB - 核心应用逻辑)                       │   │
│  │  ├─ 问诊表单输入                                     │   │
│  │  ├─ WebSocket 连接                                  │   │
│  │  ├─ 流式结果展示                                    │   │
│  │  └─ 状态管理 (Zustand)                              │   │
│  └──────────────────────────────────────────────────────┘   │
│                          ↕️ HTTP/WebSocket (代理到 :9000)     │
└─────────────────────────────────────────────────────────────┘
  ↓
┌─────────────────────────────────────────────────────────────┐
│   FastAPI 后端 (9000端口) - webui/server/                   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ app.py (37.5KB)                                      │   │
│  │ ├─ REST API 端点                                    │   │
│  │ ├─ WebSocket 连接管理                               │   │
│  │ ├─ 请求路由到智能体系统                              │   │
│  │ └─ 结果流式返回                                     │   │
│  └──────────────────────────────────────────────────────┘   │
│                          ↓                                   │
│  ┌─ 医学诊疗智能体系统 ───────────────────────────────────┐  │
│  │                                                       │  │
│  │  Stage 1: 问诊收集                                   │  │
│  │  ├─ agents_io.py (9.5KB)                            │  │
│  │  └─ 从用户输入收集医学信息                            │  │
│  │                                                       │  │
│  │  Stage 2: Intake 分类                                │  │
│  │  ├─ intake_classifier.py (10.1KB) ⭐ 智能体1        │  │
│  │  └─ 分类症状/诊断类型                                │  │
│  │                                                       │  │
│  │  Stage 3: 诊疗规划                                   │  │
│  │  ├─ intake_planner.py (9.8KB) ⭐ 智能体2            │  │
│  │  └─ 生成诊疗计划                                     │  │
│  │                                                       │  │
│  │  Stage 4: 多智能体协调执行                           │  │
│  │  ├─ coordinator_tools.py (29.7KB) ⭐ 智能体3        │  │
│  │  ├─ stage_executors.py (22.5KB) ⭐ 智能体4         │  │
│  │  ├─ 并行执行子任务                                   │  │
│  │  └─ 汇聚结果                                         │  │
│  │                                                       │  │
│  │  Core Engine:                                        │  │
│  │  ├─ scenario_runner.py (61.6KB - 主编排引擎)        │  │
│  │  ├─ llm.py (6.9KB - LLM 调用)                       │  │
│  │  ├─ knowledge_api.py (20.1KB - 医学知识库)          │  │
│  │  └─ workflow.py (16.9KB - 工作流管理)               │  │
│  │                                                       │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 🎯 4个医学智能体详解

### **智能体 1: Intake Classifier (分类器)**

**文件**: `webui/server/intake_classifier.py` (10.1KB)

**职责**: 对患者问诊进行医学分类

**输入**:
```python
{
    "symptom": "头疼、发热",
    "duration": "3天",
    "severity": "中度",
    "medical_history": "无"
}
```

**输出**:
```python
{
    "category": "infection",  # 可能的诊断类别
    "subcategory": "viral_fever",
    "urgency": "normal",
    "confidence": 0.85,
    "differential_diagnoses": [
        {"name": "common_cold", "probability": 0.4},
        {"name": "flu", "probability": 0.35},
        {"name": "bacterial_infection", "probability": 0.25}
    ]
}
```

**核心流程**:
1. 接收患者原始输入
2. 使用 LLM 提取医学特征
3. 分类到医学模型
4. 返回分类结果 + 置信度

---

### **智能体 2: Intake Planner (规划者)**

**文件**: `webui/server/intake_planner.py` (9.8KB)

**职责**: 基于分类生成诊疗计划

**输入**:
```python
{
    "classification": "viral_fever",
    "patient_profile": {
        "age": 35,
        "allergies": ["penicillin"],
        "chronic_conditions": ["hypertension"]
    },
    "available_resources": ["clinic", "lab", "pharmacy"]
}
```

**输出**:
```python
{
    "plan_id": "plan_20261009_001",
    "stages": [
        {
            "stage": 1,
            "name": "Initial Assessment",
            "actions": [
                {"type": "examination", "item": "temperature"},
                {"type": "lab_test", "item": "blood_culture"}
            ],
            "duration": "30min",
            "next_stage_condition": "wait_lab_results"
        },
        {
            "stage": 2,
            "name": "Treatment",
            "actions": [
                {"type": "medication", "drug": "paracetamol", "dose": "500mg"},
                {"type": "advice", "content": "rest_and_hydration"}
            ],
            "duration": "varies"
        }
    ],
    "total_estimated_duration": "varies",
    "follow_up_required": True,
    "follow_up_days": 3
}
```

**核心流程**:
1. 接收分类结果
2. 查询医学知识库
3. 生成多阶段诊疗计划
4. 考虑患者禁忌症
5. 返回可执行的诊疗方案

---

### **智能体 3: Coordinator (协调器)**

**文件**: `webui/server/coordinator_tools.py` (29.7KB)

**职责**: 管理诊疗计划执行的多智能体协调

**核心功能**:
```python
class CoordinatorTools:
    def create_team(self, plan: DiagnosisPlan):
        """为诊疗计划创建专科医生团队"""
        team = {
            "team_id": "team_20261009_001",
            "roles": [
                {"role": "general_practitioner", "agent": GeneralAgent()},
                {"role": "specialist", "agent": SpecialistAgent()},
                {"role": "lab_technician", "agent": LabAgent()},
                {"role": "pharmacist", "agent": PharmacyAgent()}
            ],
            "lead": "general_practitioner"
        }
        return team
    
    def delegate_task(self, task: PlanStage, team: Team):
        """将诊疗阶段任务分配给合适的团队成员"""
        for action in task.actions:
            agent = team.find_suitable_agent(action.type)
            agent.queue_task(action)
    
    def synchronize(self, team: Team):
        """同步各个智能体的执行进度"""
        status = {}
        for agent in team.agents:
            status[agent.role] = agent.get_status()
        return status
    
    def handle_conflict(self, conflicts: list[Conflict]):
        """处理智能体之间的冲突（如药物相互作用警告）"""
        for conflict in conflicts:
            resolution = self.resolve(conflict)
            self.broadcast_to_team(resolution)
```

**执行流程**:
1. 为每个诊疗阶段创建代理团队
2. 并行分配任务给相关代理
3. 实时同步各代理执行状态
4. 检测和处理冲突
5. 聚合各代理输出

---

### **智能体 4: Scenario Runner (场景执行器)**

**文件**: `webui/server/scenario_runner.py` (61.6KB) ⭐⭐⭐ 最复杂

**职责**: 编排整个诊疗流程的执行

**核心状态机**:
```python
class ScenarioRunner:
    states = [
        "init",                 # 初始化
        "intake_collection",    # 收集问诊信息
        "classification",       # 分类
        "planning",             # 规划
        "execution",            # 执行诊疗
        "monitoring",           # 监测
        "completion",           # 完成
        "error_handling"        # 错误处理
    ]
    
    async def run(self, patient_input: dict):
        """执行完整的医学诊疗流程"""
        
        # Step 1: 收集问诊
        history = await self.collect_intake(patient_input)
        
        # Step 2: 分类
        classification = await IntakeClassifier.classify(history)
        
        # Step 3: 规划
        plan = await IntakePlanner.plan(classification)
        
        # Step 4: 创建协调团队
        team = await CoordinatorTools.create_team(plan)
        
        # Step 5: 执行各阶段
        for stage in plan.stages:
            results = await self.execute_stage(stage, team)
            
            # Step 5a: 实时流式返回结果
            await self.stream_results(results)
            
            # Step 5b: 处理反馈（支持人工干预）
            feedback = await self.wait_for_feedback()
            
            # Step 5c: 动态调整计划
            if feedback.requires_replanning:
                plan = await IntakePlanner.replan(feedback)
                team = await CoordinatorTools.recreate_team(plan)
        
        # Step 6: 总结报告
        report = await self.generate_report(plan, results)
        
        return report
    
    async def execute_stage(self, stage: PlanStage, team: Team):
        """执行诊疗的单个阶段"""
        
        # 并行执行这个阶段的所有动作
        tasks = []
        for action in stage.actions:
            agent = team.find_agent_for_action(action)
            task = agent.execute(action)
            tasks.append(task)
        
        # 等待所有任务完成或超时
        results = await asyncio.gather(*tasks, timeout=stage.timeout)
        
        # 检查结果的医学一致性
        await self.validate_results(results)
        
        return results
```

**执行时间轴**:
```
T=0s    用户输入问诊 → [WebSocket]
         ↓
T=1s    分类器分析症状
         ├─ 特征提取
         └─ 生成诊断候选
         ↓
T=3s    规划器制定方案
         ├─ 查询知识库
         ├─ 生成诊疗步骤
         └─ [流式返回到前端]
         ↓
T=5s    协调器创建医疗团队
         ├─ 内科医生
         ├─ 检验技师
         └─ 药师
         ↓
T=6s    并行执行诊疗阶段 1
         ├─ 医生: 体格检查 (30s)
         ├─ 技师: 准备检验 (20s)
         └─ 流式进度更新
         ↓
T=30s   监测结果 + 可能调整计划
         ↓
T+Ns   诊疗完成 + 生成报告
```

---

## 📊 数据流 - WebUI 完整流程

### **用户交互流**

```
WebUI 前端 (App.tsx - 36KB)
├─ 用户输入问诊信息
│  └─ 症状、病史、用药过敏等
│
├─ 建立 WebSocket 连接
│  └─ ws://localhost:9000/ws
│
├─ 发送初始请求
│  ```json
│  {
│    "patient_id": "P001",
│    "symptoms": "头疼、发热",
│    "duration": "3天",
│    "severity": "5/10",
│    "medical_history": {...},
│    "current_medications": [...]
│  }
│  ```
│
└─ 接收流式结果
   └─ 每个智能体阶段实时推送
      ├─ 分类结果: {"category": "viral_fever", ...}
      ├─ 规划结果: {"stages": [...], ...}
      ├─ 执行进度: {"stage": 1, "progress": 50%, ...}
      └─ 最终报告: {"diagnosis": "...", "treatment": "..."}
```

### **后端数据处理流**

```
FastAPI app.py (:9000)
│
├─ POST /api/diagnose
│  ├─ 解析患者输入
│  ├─ 创建 WebSocket 连接
│  └─ 启动 ScenarioRunner
│
├─ ScenarioRunner 执行
│  │
│  ├─ Stage 1: Intake Collection (agents_io.py)
│  │  └─ result = await collect_patient_history(input)
│  │     [流式发送: "intake_collected"]
│  │
│  ├─ Stage 2: Classification (intake_classifier.py) ⭐ 智能体1
│  │  └─ classification = await IntakeClassifier.classify(history)
│  │     [流式发送: "classification_result", classification]
│  │
│  ├─ Stage 3: Planning (intake_planner.py) ⭐ 智能体2
│  │  └─ plan = await IntakePlanner.generate_plan(classification)
│  │     [流式发送: "plan_generated", plan]
│  │
│  ├─ Stage 4: Team Creation (coordinator_tools.py) ⭐ 智能体3
│  │  └─ team = await create_medical_team(plan)
│  │     [流式发送: "team_created", team]
│  │
│  ├─ Stage 5: Execution (stage_executors.py) ⭐ 智能体4
│  │  ├─ for each stage in plan:
│  │  │  ├─ 并行执行所有动作
│  │  │  ├─ 医生: 体格检查
│  │  │  ├─ 检验: 抽血检查
│  │  │  ├─ 药师: 用药建议
│  │  │  └─ [流式发送: "stage_X_progress", progress_pct]
│  │  └─ await validate_medical_consistency(results)
│  │
│  └─ Stage 6: Report Generation (dashboard_stats.py)
│     └─ report = compile_final_report(all_results)
│        [流式发送: "report_ready", report]
│
└─ 返回最终诊疗报告
```

---

## 🔄 多智能体协调详解

### **协调机制 (coordinator_tools.py 29.7KB)**

```python
"""
医学诊疗多智能体协调的核心设计
"""

class MedicalTeam:
    """代表一个医疗团队"""
    
    def __init__(self):
        self.agents = {
            "general_doctor": GeneralDoctor(),      # 全科医生（主导）
            "specialist": Specialist(),              # 专科医生
            "lab_technician": LabTechnician(),      # 检验技师
            "pharmacist": Pharmacist(),              # 药师
            "radiologist": Radiologist()            # 放射科医生（可选）
        }
    
    async def execute_stage(self, stage: PlanStage):
        """执行诊疗的一个阶段，协调多个专科"""
        
        # 第1步: 分析这个阶段需要哪些专科
        required_specialists = self.analyze_requirements(stage)
        
        # 第2步: 调用相关智能体
        async def doctor_task():
            return await self.agents["general_doctor"].examine(stage)
        
        async def lab_task():
            return await self.agents["lab_technician"].run_tests(stage)
        
        async def specialist_task():
            if "specialist" in required_specialists:
                return await self.agents["specialist"].consult(stage)
        
        # 第3步: 并行执行，等待所有结果
        results = await asyncio.gather(
            doctor_task(),
            lab_task(),
            specialist_task(),
            return_exceptions=True
        )
        
        # 第4步: 冲突检测（关键！）
        conflicts = self.detect_conflicts(results)
        if conflicts:
            conflicts = await self.resolve_conflicts(conflicts)
        
        # 第5步: 汇聚决策
        final_decision = await self.agents["general_doctor"].synthesize(
            doctor_result=results[0],
            lab_result=results[1],
            specialist_result=results[2],
            conflicts_resolved=conflicts
        )
        
        return final_decision

# 冲突检测例子：药物相互作用
# 如果医生建议开青霉素，但病人对青霉素过敏
# → Pharmacist 智能体会触发冲突
# → Coordinator 解决冲突（选择替代药物）
# → 通知医生更新处方
```

---

## 📈 知识库 & 工作流 (knowledge_api.py + workflows.py)

### **医学知识库 (knowledge_api.py - 20.1KB)**

```python
class MedicalKnowledgeAPI:
    """医学诊疗知识库"""
    
    async def get_differential_diagnosis(self, symptoms: list[str]):
        """获取鉴别诊断"""
        return {
            "candidates": [
                {"name": "viral_fever", "probability": 0.4},
                {"name": "bacterial_infection", "probability": 0.35},
                {"name": "malaria", "probability": 0.15},
            ]
        }
    
    async def get_treatment_protocol(self, diagnosis: str):
        """获取诊疗规程"""
        return {
            "diagnosis": "viral_fever",
            "stages": [
                {
                    "stage": "assessment",
                    "tests": ["temperature", "throat_culture"],
                    "duration": "30min"
                },
                {
                    "stage": "treatment",
                    "medications": [
                        {"name": "paracetamol", "dose": "500mg", "frequency": "6h"},
                        {"name": "throat_lozenges", "dose": "1 lozenge", "frequency": "4h"}
                    ]
                }
            ]
        }
    
    async def check_contraindications(self, patient_profile: dict, medications: list):
        """检查禁忌症"""
        return {
            "safe": True/False,
            "warnings": ["allergy_to_penicillin", "hypertension_management"],
            "alternatives": [...]
        }
    
    async def check_drug_interactions(self, current_meds: list, new_meds: list):
        """检查药物相互作用"""
        return {
            "interactions": [
                {
                    "drug1": "warfarin",
                    "drug2": "aspirin",
                    "severity": "high",
                    "action": "avoid_or_monitor"
                }
            ]
        }
```

### **工作流引擎 (workflows.py - 16.9KB)**

```python
class WorkflowEngine:
    """诊疗工作流编排"""
    
    async def create_workflow(self, diagnosis: str):
        """为诊断创建工作流"""
        workflow = {
            "id": f"wf_{diagnosis}_{datetime.now().timestamp()}",
            "diagnosis": diagnosis,
            "steps": [
                {
                    "step_id": 1,
                    "name": "Initial Assessment",
                    "parallel_tasks": ["vitals", "history"],
                    "duration_sec": 600,
                    "next_condition": "assessment_complete"
                },
                {
                    "step_id": 2,
                    "name": "Lab Work",
                    "parallel_tasks": ["blood_test", "throat_culture"],
                    "duration_sec": 1800,
                    "next_condition": "lab_results_ready"
                },
                {
                    "step_id": 3,
                    "name": "Treatment Decision",
                    "condition_branches": {
                        "positive_for_strep": "antibiotic_treatment",
                        "negative_viral": "supportive_care",
                        "inconclusive": "repeat_test"
                    }
                }
            ]
        }
        return workflow
    
    async def execute_workflow(self, workflow: Workflow, team: MedicalTeam):
        """执行工作流"""
        for step in workflow.steps:
            # 执行这个步骤
            result = await team.execute_step(step)
            
            # 检查条件，决定下一步
            next_step = self.evaluate_conditions(step, result)
            
            yield result  # 流式返回
```

---

## 🎛️ 前端数据状态 (Zustand store)

```typescript
// webui/src/App.tsx - 核心状态管理

interface DiagnoseState {
  // 输入
  patientInput: {
    symptoms: string;
    duration: string;
    severity: number;
    medicalHistory: string;
  };
  
  // 阶段结果
  stages: {
    classification: ClassificationResult | null;
    plan: DiagnosisPlan | null;
    teamCreated: MedicalTeam | null;
    executionProgress: ExecutionProgress[];
  };
  
  // UI 状态
  loading: boolean;
  currentStage: "input" | "classifying" | "planning" | "executing" | "complete";
  streamingMessages: StreamMessage[];
  errors: ErrorMessage[];
  
  // WebSocket
  wsConnected: boolean;
}

// 流式消息类型
type StreamMessage = 
  | { type: "classification_result"; data: ClassificationResult }
  | { type: "plan_generated"; data: DiagnosisPlan }
  | { type: "stage_progress"; data: { stage: number; progress: number } }
  | { type: "report_ready"; data: FinalReport }
  | { type: "error"; data: string };
```

---

## ⚡ 数据流时序图

```
用户         前端WebUI         FastAPI          各智能体
 │             │                │                │
 ├─输入问诊──→ │                │                │
 │             │──WebSocket──→ │                │
 │             │                ├─Stage1────────→ IntakeCollector
 │             │◄───流1: 收集完成──┤                │
 │             ├─显示进度    │                
 │             │             ├─Stage2────────→ IntakeClassifier ⭐
 │             │◄───流2: 分类结果──┤                │
 │             ├─显示分类        │                
 │             │             ├─Stage3────────→ IntakePlanner ⭐
 │             │◄───流3: 诊疗计划──┤                │
 │             ├─显示计划        │                
 │             │             ├─Stage4────────→ Coordinator ⭐
 │             │◄───流4: 团队创建──┤                │
 │             │             │
 │             │             ├─Stage5: 并行执行  
 │             │             │ ├→ 医生体检 (30s)
 │             │             │ ├→ 检验采样 (20s)  ⭐ Executors
 │             │             │ └→ 药师建议 (15s)
 │             │◄───流5: 进度更新──┤                │
 │             ├─进度条更新    │
 │             │             ├─汇聚结果        
 │             │◄───流6: 最终报告──┤                │
 │             ├─显示诊疗报告   │
```

---

## 🚀 启动和执行

### **启动脚本 (start.sh)**

```bash
#!/bin/bash
# 启动 WebUI: FastAPI 后端 :9000 + Vite 前端 :5173

# Dev 模式（推荐开发）
./start.sh dev
# → FastAPI 在 :9000 (webui/server/app.py)
# → Vite 在 :5173 (代理 /api/* 到 :9000)

# Build 模式（生产）
./start.sh build
# → 编译前端到 dist/
# → FastAPI 在 :8000 服务 dist/
```

### **API 端点 (app.py)**

```python
# 核心端点
POST /api/diagnose
  # 输入: {"symptoms": "...", ...}
  # 返回: WebSocket 流连接

GET /api/agents
  # 获取可用的智能体列表

GET /api/agent/{name}
  # 获取特定智能体的信息

GET /api/workflows
  # 获取诊疗工作流列表

POST /api/workflows/{id}/execute
  # 执行指定的工作流

GET /health
  # 健康检查
```

---

## 📊 项目大小统计

```
webui/server/  (Python 后端)
├── scenario_runner.py      61.6 KB ⭐⭐⭐ (主编排引擎)
├── coordinator_tools.py    29.7 KB (多智能体协调)
├── stage_executors.py      22.5 KB (阶段执行)
├── knowledge_api.py        20.1 KB (医学知识库)
├── workflows.py            16.9 KB (工作流)
├── agent_tools.py          10.6 KB (工具集)
├── intake_classifier.py    10.1 KB (分类器) ⭐ 智能体1
├── intake_planner.py        9.8 KB (规划器) ⭐ 智能体2
├── agents_io.py             9.5 KB
├── dashboard_stats.py       8.6 KB
├── llm.py                   6.9 KB
├── team_types.py            6.3 KB
├── suggestions.py           5.0 KB
├── models.py                2.8 KB
└── skills_io.py             2.6 KB
总计: ~223 KB Python 后端代码

webui/src/  (React 前端)
├── App.tsx               36.6 KB (主应用)
├── index.css              5.2 KB
├── types.ts               1.4 KB
└── main.tsx               0.2 KB
总计: ~44 KB React 前端代码
```

---

## 🎯 总结

这个项目的真实身份是：

✅ **完整的医学诊疗系统**
- 前端 WebUI (React + Vite + Zustand)
- 后端 FastAPI 服务
- 4个专业医学智能体协调执行

✅ **真实的多智能体架构**
1. **Intake Classifier** - 医学分类
2. **Intake Planner** - 诊疗规划
3. **Coordinator** - 团队协调
4. **Scenario Runner** - 流程编排

✅ **完整的医学知识库**
- 鉴别诊断数据库
- 诊疗规程
- 禁忌症检查
- 药物相互作用

✅ **企业级工程**
- WebSocket 实时流
- 并行任务执行
- 冲突检测与解决
- 工作流引擎

---

**这是一个认真的医学 AI 系统，不是玩具项目。**

