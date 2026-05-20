from kg.taxonomy import extract_entities, normalize_skill


def test_normalize_skill_aliases():
    assert normalize_skill("pytorch") == "PyTorch"
    assert normalize_skill("ml") == "机器学习"
    assert normalize_skill("unknown") is None


def test_extract_entities_from_tags_and_description():
    result = extract_entities(
        title="大模型算法工程师",
        tags="python,pytorch,带薪年假,弹性工作,数据分析",
        description="负责 LLM 应用与机器学习模型训练",
    )

    assert "Python" in result.skills
    assert "PyTorch" in result.skills
    assert "大模型" in result.skills
    assert "机器学习" in result.skills
    assert "带薪年假" in result.benefits
    assert "弹性工作" in result.benefits
    assert "数据分析" in result.skills


def test_extract_entities_avoids_false_positive_java_from_javascript():
    result = extract_entities(
        title="前端开发工程师",
        tags="javascript,css,html",
        description="负责 JavaScript 前端交互开发",
    )

    assert "JavaScript" in result.skills
    assert "Java" not in result.skills


def test_extract_entities_normalizes_benefit_aliases():
    result = extract_entities(
        title="算法工程师",
        tags="年终奖,双休,有餐补",
        description="负责机器学习系统开发",
    )

    assert "年终奖金" in result.benefits
    assert "周末双休" in result.benefits
    assert "餐饮补贴" in result.benefits
