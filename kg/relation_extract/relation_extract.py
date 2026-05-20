import json
import re
import spacy
import torch
import itertools
from transformers import pipeline
import logging
import os

logging.basicConfig(level=logging.INFO)

# ==========================================
# 1. 初始化最强非 LLM 模型
# ==========================================
print("正在加载句法分析模型和语义分类模型，请稍候...")
import warnings
warnings.filterwarnings("ignore")

try:
    nlp = spacy.load("zh_core_web_trf")
except OSError:
    print("未找到 zh_core_web_trf 模型，请先运行: python -m spacy download zh_core_web_trf")
    exit()

device = 0 if torch.cuda.is_available() else -1
zero_shot_classifier = pipeline(
    "zero-shot-classification", 
    model="MoritzLaurer/mDeBERTa-v3-base-mnli-xnli",
    device=device
)
print("模型加载完成！\n" + "="*40)


# ==========================================
# 2. 定义级联抽取管线类
# ==========================================
class RelationExtractor:
    def __init__(self, confidence_threshold=0.65, max_distance=35):
        self.threshold = confidence_threshold
        self.max_distance = max_distance

        self.lexicon = {
            "co_occurrence": r"(?:、|/|和|与|及|以及|,|，|\s+)",
            "include_forward": r"(?:包括但不限于|包括|包含|涵盖|如|比如|分为|：|:)",
            "include_backward": r"(?:等|等相关|等基础)",
            "apply_to": r"(?:用于|进行|实现|支撑|赋能|提升|开发|处理)" 
        }

    def _get_entity_positions(self, text, e1, e2):
        pos1 = text.find(e1)
        pos2 = text.find(e2)
        if pos1 == -1 or pos2 == -1: return None
        if pos1 < pos2:
            return {"left": e1, "left_pos": pos1, "right": e2, "right_pos": pos2, "original": (e1, e2)}
        else:
            return {"left": e2, "left_pos": pos2, "right": e1, "right_pos": pos1, "original": (e1, e2)}

    def extract_by_rule(self, text, e_info):
        left_e, right_e = re.escape(e_info["left"]), re.escape(e_info["right"])
        gap_pattern = r"[^,。;；\n]{0,20}?"

        if re.search(rf"{left_e}{gap_pattern}{self.lexicon['co_occurrence']}{gap_pattern}{right_e}", text):
            return "Co_Occurrence", e_info["left"], e_info["right"]
        if re.search(rf"{left_e}{gap_pattern}{self.lexicon['include_forward']}{gap_pattern}{right_e}", text):
            return "Include", e_info["left"], e_info["right"]
        if re.search(rf"{left_e}{gap_pattern}{self.lexicon['include_backward']}{gap_pattern}{right_e}", text):
            return "Include", e_info["right"], e_info["left"]
        if re.search(rf"{left_e}{gap_pattern}{self.lexicon['apply_to']}{gap_pattern}{right_e}", text):
            return "Apply_To", e_info["left"], e_info["right"]

        if re.search(rf"{left_e}[^,。;；\n]{{0,5}}?[:：][^,。;；\n]{{0,30}}?{right_e}", text):
            return "Include", e_info["left"], e_info["right"]
        
        return None, e_info["original"][0], e_info["original"][1]

    def extract_by_syntax(self, text, e_info, sub, obj):
        import networkx as nx
        
        doc = nlp(text)
        
        def get_head_token(ent_text, start_char):
            end_char = start_char + len(ent_text)
            span = doc.char_span(start_char, end_char, alignment_mode="expand")
            return span.root if span else None

        e_left_token = get_head_token(e_info["left"], e_info["left_pos"])
        e_right_token = get_head_token(e_info["right"], e_info["right_pos"])

        if not e_left_token or not e_right_token:
            return None, sub, obj

        # ==========================================
        #构建句法依存无向图并寻找 SDP
        # ==========================================
        edges = []
        for token in doc:
            for child in token.children:
                edges.append((token.i, child.i))
                
        # 生成无向图
        graph = nx.Graph(edges)

        try:
            # 获取实体核心词之间的最短路径 
            path_indices = nx.shortest_path(graph, source=e_left_token.i, target=e_right_token.i)
        except nx.NetworkXNoPath:
            return None, sub, obj
        except nx.NodeNotFound:
            return None, sub, obj

        path_length = len(path_indices) - 1

        # 规则 1：如果两个实体在句法树上相隔太远 (大于4跳)，说明没有直接逻辑关系
        if path_length > 4:
            return None, sub, obj

        # 获取路径上的所有 Token 对象
        path_tokens = [doc[i] for i in path_indices]
        
        # 提取路径上的句法依赖标签 (dep_) 和 词性 (pos_)
        path_deps = [t.dep_ for t in path_tokens]
        path_pos = [t.pos_ for t in path_tokens]

        # ==========================================
        # 基于 SDP 路径特征进行关系推断
        # ==========================================
        
        # 判定 A：并列关系
        # 如果路径中包含 'conj' (并列)，通常代表 A 和 B 是同级关系
        if 'conj' in path_deps:
            return "Co_Occurrence", sub, obj # (SDP并列关系)

        # 判定 B：应用/目的关系
        # 如果路径中包含 动词(VERB) 或者 介宾/动宾关系 (prep, pobj, dobj)
        # 例如路径是：实体A -> (pobj)介词 -> (prep)动词 -> (dobj)实体B
        if path_length <= 3:
            if any(dep in path_deps for dep in ['prep', 'pobj', 'dobj', 'nmod']):
                # 1. 获取左右实体各自在句子中的具体语法角色
                left_dep = e_left_token.dep_
                right_dep = e_right_token.dep_
                # 2. 如果右实体是动词的宾语(dobj) 或 介词的宾语(pobj) (如 "选用[C++]")
                # 说明右实体是工具，方向应该是：右实体 -> 应用于 -> 左实体
                if right_dep in ['dobj', 'pobj']:
                    return "Apply_To", e_info["right"], e_info["left"]
                # 3. 如果左实体是宾语 (如 "使用[C++]开发系统")
                # 说明左实体是工具，方向应该是：左实体 -> 应用于 -> 右实体
                elif left_dep in ['dobj', 'pobj']:
                    return "Apply_To", e_info["left"], e_info["right"]
                # 4. 如果没分出胜负，默认按照原文本出现的先后顺序
                # 在中文习惯中，"A...用于...B"，A大概率是工具。
                else:
                    return "Apply_To", e_info["left"], e_info["right"]  

        # 判定 C：如果相距仅1跳，且是复合词从属关系
        if path_length == 1 and 'compound' in path_deps:
            return "Apply_To", sub, obj  # (SDP复合词修饰)

        return None, sub, obj

    def extract_by_semantic(self, text, e_info, sub, obj):
        left, left_pos = e_info["left"], e_info["left_pos"]
        right, right_pos = e_info["right"], e_info["right_pos"]
        
        # 给文本打上标记，帮助模型定位
        marked_text = text[:right_pos] + f"“{right}”" + text[right_pos+len(right):]
        marked_text = marked_text[:left_pos] + f"“{left}”" + marked_text[left_pos+len(left):]

        #优化候选标签，提供更自然的句子，并加入方向性判断
        candidate_labels = [
            f"“{left}”和“{right}”属于并列的同类概念",
            f"使用“{left}”技术应用于“{right}”",
            f"使用“{right}”技术应用于“{left}”",
            f"“{left}”中包含了“{right}”",
            f"“{right}”中包含了“{left}”",
            f"“{left}”和“{right}”之间没有明显的逻辑关系"
        ]
        
        # 调用零样本分类
        result = zero_shot_classifier(marked_text, candidate_labels)
        best_label = result['labels'][0]
        best_score = result['scores'][0]
        
        # 提高阈值，如果模型不确定，宁可判断为 None 也不要乱猜
        if best_score > self.threshold:
            if "并列" in best_label:
                return "Co_Occurrence", left, right
            elif "应用于" in best_label:
                # 谁应用于谁？解析模型选出的方向
                if best_label.startswith(f"使用“{left}”"):
                    return "Apply_To", left, right
                else:
                    return "Apply_To", right, left
            elif "包含" in best_label:
                # 解析包含方向
                if best_label.startswith(f"“{left}”"):
                    return "Include", left, right
                else:
                    return "Include", right, left
                    
        return "None", sub, obj

    def process_pair(self, text, e1, e2):
        e_info = self._get_entity_positions(text, e1, e2)
        if not e_info: return "None", e1, e2, "None"
        
        # 1. 距离绝对截断
        distance = e_info["right_pos"] - (e_info["left_pos"] + len(e_info["left"]))
        if distance > self.max_distance:
            return "None", e1, e2, "None"

        # ==========================================
        # 2. 第一层：规则层
        # ==========================================
        rel, sub, obj = self.extract_by_rule(text, e_info)
        if rel: return rel, sub, obj, "Rule"

        # ==========================================
        # 3. 智能标点阻断
        # ==========================================
        gap_text = text[e_info["left_pos"] + len(e_info["left"]) : e_info["right_pos"]]
        
        if ':' in gap_text or '：' in gap_text:
            return "None", e1, e2, "None"
            
        if (',' in gap_text or '，' in gap_text) and distance > 15:
            return "None", e1, e2, "None"

        # ==========================================
        # 4. 第二层：句法层
        # ==========================================
        rel, sub, obj = self.extract_by_syntax(text, e_info, sub, obj)
        if rel: return rel, sub, obj, "Syntax"

        # ==========================================
        # 5. 第三层：语义层
        # ==========================================
        rel, sub, obj = self.extract_by_semantic(text, e_info, sub, obj)
        if rel != "None": return rel, sub, obj, "Semantic"
        
        return "None", sub, obj, "None"


def process_json_data(json_data, extractor, record_idx):
    text = json_data.get("jobDescription", "")
    entity_words = [item["word"] for item in json_data.get("namedEntity", [])]
    
    raw_sentences = re.split(r'[。；;\n]+', text)
    sentences = [re.sub(r'^\d+[、\.]\s*', '', s.strip()) for s in raw_sentences if len(s.strip()) > 5]

    #建立字典暂存当前 JD 各个阶段的抽取结果
    categorized_results = {
        "Rule": [],
        "Syntax": [],
        "Semantic": [],
        "Final": []
    }

    for sentence in sentences:
        entities_in_sentence = list(set([word for word in entity_words if word in sentence]))
        if len(entities_in_sentence) < 2: continue
        
        pairs = list(itertools.combinations(entities_in_sentence, 2))
        for e1, e2 in pairs:
            if e1 in e2 or e2 in e1: continue
                
            # 获取返回值和命中来源
            relation, sub, obj, stage = extractor.process_pair(sentence, e1, e2)
            
            if relation != "None":
                clean_relation = relation.split(" ")[0]
                
                # 构造要保存的通用结构字典
                result_record = {
                    "record_index": record_idx, # 记录属于原数据的第几条
                    "sentence": sentence,
                    "subject": sub,
                    "relation": clean_relation,
                    "object": obj,
                    "matched_detail": relation # 比如保留 "Apply_To (句法修饰)" 等详细信息
                }
                
                # 追加到总结果和对应的阶段结果中
                categorized_results["Final"].append(result_record)
                categorized_results[stage].append(result_record)

    return categorized_results


if __name__ == "__main__":
    # 加载测试数据
    try:
        with open("llm_direct_result.json", "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print("未找到测试数据，生成模拟测试用例...")
        data = [{
            "jobDescription": "熟悉C++、Java等主流编程语言；\n负责开发多传感器融合系统，包含视觉检测。\n熟练使用OpenCV进行图像处理开发。",
            "namedEntity": [{"word":"C++"},{"word":"Java"},{"word":"编程语言"},{"word":"多传感器融合系统"},{"word":"视觉检测"},{"word":"OpenCV"},{"word":"图像处理开发"}]
        }]
    
    extractor = RelationExtractor(confidence_threshold=0.65, max_distance=35)
    
    # 【修改点】创建全局字典，收集所有数据的四个阶段结果
    all_results = {
        "Rule": [],
        "Syntax": [],
        "Semantic": [],
        "Final": []
    }

    # 执行抽取
    for idx, item in enumerate(data):
        print(f"处理第 {idx+1}/{len(data)} 条记录...")
        current_results = process_json_data(item, extractor, idx + 1)
        
        # 将当前记录的结果汇总到全局大字典中
        for key in all_results.keys():
            all_results[key].extend(current_results[key])

    # ==========================================
    # 4. 保存为四个不同的 JSON 文件
    # ==========================================
    output_dir = "./extraction_results_llm"
    os.makedirs(output_dir, exist_ok=True) # 创建专门保存结果的文件夹

    file_mapping = {
        "Rule": "step1_rule_results.json",
        "Syntax": "step2_syntax_results.json",
        "Semantic": "step3_semantic_results.json",
        "Final": "final_kg_triplets.json"
    }

    print("\n" + "="*40)
    print("开始导出 JSON 文件...")
    
    for stage, filename in file_mapping.items():
        filepath = os.path.join(output_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            # ensure_ascii=False 确保中文正常显示，indent=4 使 JSON 格式化便于人工查看
            json.dump(all_results[stage], f, ensure_ascii=False, indent=4)
        print(f"✅ [{stage}] 阶段提取了 {len(all_results[stage])} 对关系，已保存至: {filepath}")
    
    print("="*40)
    print("全部执行完毕！")
