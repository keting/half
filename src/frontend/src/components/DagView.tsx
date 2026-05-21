import React, { useMemo, useCallback } from 'react';
import ReactFlow, {
  Background,
  Controls,
  Node,
  Edge,
  Handle,
  Position,
  MarkerType,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { Task } from '../types';

const EDGE_COLOR = '#94a3b8';

const HIDDEN_HANDLE_STYLE: React.CSSProperties = {
  width: 1,
  height: 1,
  minWidth: 1,
  minHeight: 1,
  opacity: 0,
  border: 0,
  pointerEvents: 'none',
};

function TaskNode({ data }: { data: { label: React.ReactNode } }) {
  return (
    <>
      <Handle id="top-target" type="target" position={Position.Top} style={HIDDEN_HANDLE_STYLE} />
      <Handle id="bottom-target" type="target" position={Position.Bottom} style={HIDDEN_HANDLE_STYLE} />
      <Handle id="top-source" type="source" position={Position.Top} style={HIDDEN_HANDLE_STYLE} />
      <Handle id="bottom-source" type="source" position={Position.Bottom} style={HIDDEN_HANDLE_STYLE} />
      {data.label}
    </>
  );
}

const nodeTypes = { task: TaskNode };

const STATUS_COLORS: Record<string, string> = {
  pending_blocked: '#94a3b8',
  pending_ready: '#eab308',
  running: '#f97316',
  completed: '#22c55e',
  needs_attention: '#ef4444',
  abandoned: '#64748b',
  frozen: '#94a3b8',
  unlocked: '#eab308',
  waiting_review: '#3b82f6',
  waiting_decision: '#3b82f6',
  needs_fix: '#ef4444',
  approved: '#22c55e',
};

const STATUS_BACKGROUNDS: Record<string, string> = {
  pending_blocked: '#f1f5f9',
  pending_ready: '#fef9c3',
  running: '#fff7ed',
  completed: '#ecfdf5',
  needs_attention: '#fef2f2',
  abandoned: '#e2e8f0',
  frozen: '#f1f5f9',
  unlocked: '#fef9c3',
  waiting_review: '#eff6ff',
  waiting_decision: '#eff6ff',
  needs_fix: '#fef2f2',
  approved: '#ecfdf5',
};

interface Props {
  tasks: Task[];
  selectedTaskId?: number | null;
  onSelectTask: (taskId: number) => void;
  missingPredecessorIds?: Set<number>;
  showIssueReviewLoopEdge?: boolean;
}

function computeLayout(tasks: Task[]): Map<string, { x: number; y: number }> {
  const taskMap = new Map<string, Task>();
  tasks.forEach((t) => taskMap.set(t.task_code, t));

  const depths = new Map<string, number>();

  function getDepth(code: string): number {
    if (depths.has(code)) return depths.get(code)!;
    const task = taskMap.get(code);
    if (!task) return 0;
    let deps: string[] = [];
    try {
      deps = JSON.parse(task.depends_on_json || '[]');
    } catch {
      deps = [];
    }
    if (deps.length === 0) {
      depths.set(code, 0);
      return 0;
    }
    const maxParent = Math.max(...deps.map((d) => getDepth(d)));
    const depth = maxParent + 1;
    depths.set(code, depth);
    return depth;
  }

  tasks.forEach((t) => getDepth(t.task_code));

  const layers = new Map<number, string[]>();
  depths.forEach((depth, code) => {
    if (!layers.has(depth)) layers.set(depth, []);
    layers.get(depth)!.push(code);
  });

  const positions = new Map<string, { x: number; y: number }>();
  const nodeWidth = 200;
  const nodeHeight = 80;
  const horizontalGap = 60;
  const verticalGap = 100;

  layers.forEach((codes, depth) => {
    const totalWidth = codes.length * nodeWidth + (codes.length - 1) * horizontalGap;
    const startX = -totalWidth / 2;
    codes.forEach((code, i) => {
      positions.set(code, {
        x: startX + i * (nodeWidth + horizontalGap),
        y: depth * (nodeHeight + verticalGap),
      });
    });
  });

  return positions;
}

function getVisualStatus(task: Task, tasks: Task[]): string {
  const businessStatus = (task as Task & { business_status?: string | null }).business_status;
  if (businessStatus) {
    return businessStatus;
  }

  if (task.status !== 'pending') {
    return task.status;
  }

  let deps: string[] = [];
  try {
    deps = JSON.parse(task.depends_on_json || '[]');
  } catch {
    deps = [];
  }

  if (deps.length === 0) {
    return 'pending_ready';
  }

  const predecessorTasks = tasks.filter((candidate) => deps.includes(candidate.task_code));
  const isReady = deps.every((depCode) => {
    const predecessor = predecessorTasks.find((candidate) => candidate.task_code === depCode);
    return predecessor && (predecessor.status === 'completed' || predecessor.status === 'abandoned');
  });
  return isReady ? 'pending_ready' : 'pending_blocked';
}

export default function DagView({ tasks, selectedTaskId, onSelectTask, missingPredecessorIds, showIssueReviewLoopEdge }: Props) {
  const { initialNodes, initialEdges } = useMemo(() => {
    const positions = computeLayout(tasks);

    const nodes: Node[] = tasks.map((task) => {
      const pos = positions.get(task.task_code) || { x: 0, y: 0 };
      const visualStatus = getVisualStatus(task, tasks);
      const statusColor = STATUS_COLORS[visualStatus] || '#9ca3af';
      const isSelected = task.id === selectedTaskId;
      const isMissing = missingPredecessorIds?.has(task.id) ?? false;

      return {
        id: String(task.id),
        type: 'task',
        position: pos,
        data: {
          label: (
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontWeight: 600, fontSize: '12px', marginBottom: '2px' }}>
                {task.task_code}
              </div>
              <div style={{ fontSize: '11px', color: '#555', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: '160px' }}>
                {task.task_name}
              </div>
              {(task as Task & { assignee_label?: string | null }).assignee_label && (
                <div style={{ fontSize: '10px', color: '#2563eb', marginTop: '4px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: '160px' }}>
                  {(task as Task & { assignee_label?: string | null }).assignee_label}
                </div>
              )}
            </div>
          ),
        },
        sourcePosition: Position.Bottom,
        targetPosition: Position.Top,
        style: {
          background: isMissing ? '#fee2e2' : (STATUS_BACKGROUNDS[visualStatus] || '#f8fafc'),
          border: `2px solid ${isSelected ? '#3b82f6' : (isMissing ? '#dc2626' : statusColor)}`,
          borderRadius: '8px',
          padding: '8px 12px',
          width: 180,
          cursor: 'pointer',
          boxShadow: isSelected ? '0 0 0 2px #3b82f6' : 'none',
        },
      };
    });

    const edges: Edge[] = [];
    tasks.forEach((task) => {
      let deps: string[] = [];
      try {
        deps = JSON.parse(task.depends_on_json || '[]');
      } catch {
        deps = [];
      }
      deps.forEach((depCode) => {
        const depTask = tasks.find((t) => t.task_code === depCode);
        if (depTask) {
          edges.push({
            id: `${depTask.id}-${task.id}`,
            source: String(depTask.id),
            target: String(task.id),
            sourceHandle: 'bottom-source',
            targetHandle: 'top-target',
            markerEnd: { type: MarkerType.ArrowClosed, color: EDGE_COLOR },
            style: { stroke: EDGE_COLOR },
          });
        }
      });
    });

    if (showIssueReviewLoopEdge) {
      const decisionTask = tasks.find((task) => task.task_code === 'TASK-005');
      const codingTask = tasks.find((task) => task.task_code === 'TASK-002');
      if (decisionTask && codingTask) {
        edges.push({
          id: `${decisionTask.id}-${codingTask.id}-review-loop`,
          source: String(decisionTask.id),
          target: String(codingTask.id),
          sourceHandle: 'top-source',
          targetHandle: 'bottom-target',
          markerEnd: { type: MarkerType.ArrowClosed, color: EDGE_COLOR },
          style: { stroke: EDGE_COLOR, strokeDasharray: '6 4' },
        });
      }
    }

    return { initialNodes: nodes, initialEdges: edges };
  }, [tasks, selectedTaskId, missingPredecessorIds, showIssueReviewLoopEdge]);

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      onSelectTask(Number(node.id));
    },
    [onSelectTask]
  );

  return (
    <div style={{ width: '100%', height: '100%', minHeight: 400 }}>
      <ReactFlow
        nodes={initialNodes}
        edges={initialEdges}
        nodeTypes={nodeTypes}
        onNodeClick={onNodeClick}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        proOptions={{ hideAttribution: true }}
        nodesDraggable={true}
        nodesConnectable={false}
        elementsSelectable={true}
      >
        <Controls />
        <Background gap={20} color="#e2e8f0" />
      </ReactFlow>
    </div>
  );
}
