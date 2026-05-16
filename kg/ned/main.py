"""
实体消歧入口

两条并行路径：
    python kg/ned/main.py                # 传统方法（规则词典 + 字符串聚类）
    python kg/ned/main.py --direct-llm   # 直接用 DeepSeek 大模型消歧
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from loguru import logger

from kg.ned.traditional import run_pipeline
from kg.ned.llm_direct import run_direct_llm_pipeline

DATA_DIR = ROOT / "datasets" / "knowledge_graph_result"
DEFAULT_INPUT = DATA_DIR / "ner_result" / "ner_merged_filtered.json"
DEFAULT_OUTPUT = DATA_DIR / "ned_result"


def main():
    parser = argparse.ArgumentParser(description="实体消歧流水线")
    parser.add_argument(
        "--input", type=Path, default=DEFAULT_INPUT,
        help=f"输入文件路径（默认: {DEFAULT_INPUT}）",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT,
        help=f"输出目录（默认: {DEFAULT_OUTPUT}）",
    )
    # ── 传统方法参数 ──────────────────────────────────────────────────────
    parser.add_argument(
        "--fuzzy-threshold", type=float, default=0.85,
        help="传统方法字符串聚类阈值（默认: 0.85）",
    )
    # ── 直接 LLM 消歧参数 ────────────────────────────────────────────────
    parser.add_argument(
        "--direct-llm", action="store_true",
        help="直接用 DeepSeek 大模型消歧（跳过传统方法）",
    )
    parser.add_argument(
        "--max-batch-size", type=int, default=100,
        help="LLM 消歧每批最多实体数（默认: 100）",
    )
    parser.add_argument(
        "--context", type=str,
        default="AI岗位招聘数据，实体来自职位描述",
        help="提供给大模型的上下文提示（仅 --direct-llm 模式）",
    )
    args = parser.parse_args()

    logger.remove()
    logger.add(sys.stderr, level="INFO", colorize=True)

    if args.direct_llm:
        summary = run_direct_llm_pipeline(
            input_path=args.input,
            output_dir=args.output_dir,
            context=args.context,
            max_batch_size=args.max_batch_size,
        )
        print("\n=== 直接 LLM 消歧完成 ===")
        print(f"输入记录数: {summary['input_records']}")
        print(f"输出记录数: {summary['output_records']}")
        print(f"唯一实体数: {summary['total_unique_entities']}")
        print(f"合并对数: {summary['merged_pairs']}")
        print(f"LLM 分组数: {summary['llm_groups']}")
        print(f"耗时: {summary['time_seconds']}s")
    else:
        summary = run_pipeline(
            input_path=args.input,
            output_dir=args.output_dir,
            fuzzy_threshold=args.fuzzy_threshold,
        )
        print("\n=== 传统消歧完成 ===")
        print(f"输入记录数: {summary['input_records']}")
        print(f"输出记录数: {summary['output_records']}")
        print(f"传统消歧: {summary['traditional']}")


if __name__ == "__main__":
    main()
