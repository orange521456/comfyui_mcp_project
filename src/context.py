"""Shared context for MCP tools — holds current workflow state in memory."""

from dataclasses import dataclass, field


@dataclass
class Context:
    """Singleton context shared across all MCP tools."""

    current_workflow: dict | None = None
    """Current workflow JSON (ComfyUI native format)."""

    current_workflow_ir: dict | None = None
    """Original IR that was used to build the current workflow."""

    next_node_id: int = 1
    """Auto-increment counter for node IDs."""

    def get_next_id(self) -> str:
        node_id = str(self.next_node_id)
        self.next_node_id += 1
        return node_id

    def set_workflow(self, workflow: dict, ir: dict | None = None):
        self.current_workflow = workflow
        self.current_workflow_ir = ir
        self.next_node_id = max((int(k) for k in workflow if k.isdigit()), default=0) + 1

    def clear(self):
        self.current_workflow = None
        self.current_workflow_ir = None
        self.next_node_id = 1


_ctx = Context()


def get_context() -> Context:
    return _ctx