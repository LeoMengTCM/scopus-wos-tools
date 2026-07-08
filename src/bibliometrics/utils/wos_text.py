"""WOS 纯文本记录切分工具。

统一处理两种头部形态：
- 本工具输出的文件：FN/VR 头部后有空行，再接首条 ``PT `` 记录
- WOS 原始导出：头部后**无空行**，首条记录紧贴 ``VR 1.0``

历史上多处代码用 ``content.split('\\n\\nPT ')[1:]`` 切分，对第二种形态会把
首条记录连同头部一起丢弃（每个文件静默少一条文献）。请统一使用本模块。
"""

from __future__ import annotations

from typing import List


def split_wos_records(content: str) -> List[str]:
    """把 WOS 纯文本切分为记录块列表。

    返回的每个块**不含** ``PT `` 前缀（与既有 ``split('\\n\\nPT ')`` 调用方
    的块形态保持一致，即块以 ``J``/``S`` 等 PT 值开头）。
    """
    blocks = content.split('\n\nPT ')
    head = blocks[0]
    records = blocks[1:]

    # 头部块中可能粘着首条记录（原始 WOS 导出头部后无空行）
    if head.startswith('PT '):
        records.insert(0, head[3:])
    elif '\nPT ' in head:
        records.insert(0, head.split('\nPT ', 1)[1])

    return records
