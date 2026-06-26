# output/__init__.py
# src/slop_research_factory/output/__init__.py

"""
Output rendering — converts typed data into final Markdown/JSON artifacts.

Modules:
    hai_card_renderer Render :class:`HaiCard` → ``hai_card.md``.

The finalize node (``nodes/finalize_node.py``) is the sole consumer.
"""

from slop_research_factory.output.hai_card_renderer import render_hai_card

__all__ = ["render_hai_card"]
