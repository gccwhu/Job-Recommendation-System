from kg.disambiguation import (
    normalize_benefit,
    normalize_city_name,
    normalize_company_name,
    normalize_industry_name,
)


def test_normalize_city_name_variants():
    assert normalize_city_name("上海市") == "上海"
    assert normalize_city_name("上海-浦东新区") == "上海"
    assert normalize_city_name("远程") == "远程办公"


def test_normalize_company_name_suffix():
    assert normalize_company_name("前锦网络信息技术（上海）有限公司") == "前锦网络信息技术(上海)"
    assert normalize_company_name("美团") == "美团"


def test_normalize_industry_and_benefit():
    assert normalize_industry_name("电子技术/半导体/集成电路") == "电子/半导体/集成电路"
    assert normalize_industry_name("通信/电信运营、增值服务") == "通信/电信"
    assert normalize_benefit("年终奖") == "年终奖金"
    assert normalize_benefit("双休") == "周末双休"
