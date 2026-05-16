import os
from modelscope.models import Model
from modelscope.pipelines.nlp import InformationExtractionPipeline

LOCAL_MODEL_DIR = r"D:\work\Job-Recommendation-System\NER\models\siamese-uie-official\damo\nlp_structbert_siamese-uie_chinese-base"

os.environ['MODELSCOPE_ENDPOINT'] = 'https://invalid'
os.environ.pop('MODELSCOPE_CACHE', None)

model = Model.from_pretrained(
    'damo/nlp_structbert_siamese-uie_chinese-base',
    model_dir=LOCAL_MODEL_DIR,
    revision='v1.1'
)
pipe = InformationExtractionPipeline(model=model)

sample = """职位介绍岗位职责：负责开发多传感器融合的智驾感知系统，包括但不限于基于前视、环视鱼眼、BEV的视觉检测、跟踪、分割、后处理算法，基于Lidar、Radar、超声波传感器的融合算法，基于高精地图或SD地图的融合算法。硕士或以上学历，计算机科学、软件工程、计算机视觉、人工智能相关专业。熟悉C/C++编程。"""

result = pipe(sample, schema=["技能", "学历", "专业", "职责"])
print("抽取结果：", result)