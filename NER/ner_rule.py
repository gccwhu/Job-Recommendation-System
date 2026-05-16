import json
import re
from transformers import pipeline, AutoTokenizer, AutoModelForTokenClassification
import torch

# ==================== 配置 ====================
input_file = r"D:\work\Job-Recommendation-System\NER\jobs_align.json"
output_file = r"D:\work\Job-Recommendation-System\NER\ner_rule_result.json"

# 已验证的 bert4ner 模型本地路径
BERT4NER_PATH = r"D:\work\Job-Recommendation-System\NER\models\bert4ner"

# ==================== 技能词典 ====================
SKILL_DICT = [
    r"Python", r"C\+\+", r"C#", r"Java", r"JavaScript", r"TypeScript",
    r"Go", r"Rust", r"SQL", r"R", r"MATLAB", r"Scala", r"Kotlin", r"Swift",
    r"TensorFlow", r"PyTorch", r"Keras", r"Scikit-learn", r"Pandas", r"NumPy",
    r"JAX", r"MXNet", r"PaddlePaddle", r"ONNX", r"OpenCV",
    r"机器学习", r"深度学习", r"自然语言处理", r"计算机视觉", r"数据挖掘",
    r"推荐系统", r"强化学习", r"预测模型", r"大模型", r"LLM", r"NLP",
    r"AIGC", r"Stable Diffusion", r"ChatGPT", r"Transformer", r"BERT",
    r"GPT", r"GAN", r"RNN", r"CNN", r"LSTM", r"注意力机制",
    r"多传感器融合", r"BEV", r"SLAM", r"VIO", r"SFM", r"3D视觉",
    r"Lidar", r"Radar", r"激光雷达", r"毫米波雷达", r"超声波传感器",
    r"前视", r"环视鱼眼", r"目标检测", r"目标跟踪", r"语义分割",
    r"后处理算法", r"融合算法", r"路径规划", r"行为预测",
    r"Spark", r"Hadoop", r"Flink", r"Kafka", r"Hive", r"HBase",
    r"Docker", r"Kubernetes", r"K8s", r"AWS", r"Azure", r"GCP",
    r"ROS", r"ROS2", r"Gazebo", r"Simulink", r"CANoe", r"CANape",
    r"FreeRTOS", r"AUTOSAR", r"功能安全", r"ISO 26262", r"ASPICE",
    r"Linux", r"Git", r"SVN", r"Jenkins", r"JIRA", r"Confluence",
    r"CUDA", r"TensorRT", r"DeepStream",
    r"沟通能力", r"团队合作", r"项目管理", r"英语读写", r"英语口语",
]

EDUCATION_DICT = [
    "博士", "硕士", "本科", "研究生", "大专", "博士后",
    "MBA", "EMBA", "Ph.D", "Master", "Bachelor",
]

MAJOR_DICT = [
    "计算机科学", "软件工程", "计算机视觉", "人工智能", "自动化",
    "电子工程", "通信工程", "机械工程", "数学", "统计学",
    "模式识别", "机器人", "控制工程", "电子信息", "车辆工程",
]

# ==================== 加载 bert4ner 模型 ====================
print("正在加载 bert4ner 模型...")
tokenizer = AutoTokenizer.from_pretrained(BERT4NER_PATH)
model = AutoModelForTokenClassification.from_pretrained(BERT4NER_PATH)
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model.to(device)

nlp = pipeline(
    "ner",
    model=model,
    tokenizer=tokenizer,
    aggregation_strategy="simple",
    device=0 if torch.cuda.is_available() else -1
)
print("模型加载完成！")

# ==================== 辅助函数 ====================
def clean_word(word):
    return word.replace(" ", "")

def is_valid_entity(word):
    word = word.strip()
    if not word or len(word) < 2:
        return False
    if re.fullmatch(r'[\W_]+', word):
        return False
    return True

def extract_bert_entities(text):
    """用 bert4ner 抽取 ORG, LOC, PER, TIME"""
    entities = []
    if not text or not text.strip():
        return entities
    # 简单分块避免超长
    for i in range(0, len(text), 500):
        chunk = text[i:i+500]
        for e in nlp(chunk):
            tag = e["entity_group"]
            word = clean_word(e["word"])
            if tag in ["ORG", "LOC", "PER", "TIME"] and is_valid_entity(word):
                entities.append({"entity": tag, "word": word})
    return entities

def extract_skills(text):
    skills = []
    for skill in SKILL_DICT:
        pattern = re.compile(
            r'(?<![a-zA-Z\u4e00-\u9fff])' + skill + r'(?![a-zA-Z\u4e00-\u9fff])',
            re.IGNORECASE
        )
        if pattern.search(text):
            skills.append({"entity": "SKILL", "word": skill})
    return skills

def extract_education(text):
    edu = []
    for level in EDUCATION_DICT:
        if level in text:
            edu.append({"entity": "EDUCATION", "word": level})
    return edu

def extract_major(text):
    majors = []
    for major in MAJOR_DICT:
        if major in text:
            majors.append({"entity": "MAJOR", "word": major})
    return majors

def extract_duties(text):
    duties = []
    duty_verbs = ["负责", "参与", "主导", "设计", "开发", "优化",
                  "维护", "搭建", "管理", "实现", "完成", "建设"]
    for verb in duty_verbs:
        pattern = re.compile(verb + r'([^。\n；;]+)')
        matches = pattern.findall(text)
        for match in matches:
            duty_text = verb + match.strip()
            if len(duty_text) > 3:
                duties.append({"entity": "DUTY", "word": duty_text})
    return duties

def extract_entities(text):
    """混合抽取：模型 + 规则"""
    bert_entities = extract_bert_entities(text)
    rule_entities = (
        extract_skills(text) +
        extract_education(text) +
        extract_major(text) +
        extract_duties(text)
    )
    all_entities = bert_entities + rule_entities

    # 过滤无效
    valid = [e for e in all_entities if is_valid_entity(e["word"])]
    # 去重
    seen = set()
    unique = []
    for e in valid:
        key = (e["word"], e["entity"])
        if key not in seen:
            seen.add(key)
            unique.append(e)
    return unique

# ==================== 主流程 ====================
with open(input_file, "r", encoding="utf-8") as f:
    jobs = json.load(f)

print(f"开始抽取，共 {len(jobs)} 条...")
for i, job in enumerate(jobs):
    jd = job.get("jobDescription", "")
    if jd.strip():
        job["namedEntity"] = extract_entities(jd)
    else:
        job["namedEntity"] = []
    if (i + 1) % 100 == 0:
        print(f"已处理 {i+1}/{len(jobs)} 条")

with open(output_file, "w", encoding="utf-8") as f:
    json.dump(jobs, f, ensure_ascii=False, indent=2)

print(f"抽取完成，结果已保存至: {output_file}")