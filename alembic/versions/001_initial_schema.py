"""Initial schema creation"""

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    """Create initial tables."""
    # Jobs table
    op.create_table(
        'jobs',
        sa.Column('id', sa.UUID(as_uuid=True), primary_key=True),
        sa.Column('query', sa.Text(), nullable=False),
        sa.Column('status', sa.String(), default='pending'),
        sa.Column('started_at', sa.DateTime(), default=sa.func.now()),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('total_latency_ms', sa.Float(), nullable=True),
        sa.Column('final_answer', sa.Text(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('metadata', sa.JSON(), default=dict),
    )
    op.create_index('ix_jobs_status', 'jobs', ['status'])
    op.create_index('ix_jobs_created', 'jobs', ['started_at'])
    
    # Events table
    op.create_table(
        'events',
        sa.Column('id', sa.UUID(as_uuid=True), primary_key=True),
        sa.Column('job_id', sa.UUID(as_uuid=True), sa.ForeignKey('jobs.id')),
        sa.Column('agent_id', sa.String(), nullable=True),
        sa.Column('event_type', sa.String(), nullable=False),
        sa.Column('input_hash', sa.String(), nullable=True),
        sa.Column('output_hash', sa.String(), nullable=True),
        sa.Column('latency_ms', sa.Float(), default=0.0),
        sa.Column('token_count', sa.Integer(), default=0),
        sa.Column('policy_violations', sa.JSON(), default=list),
        sa.Column('data', sa.JSON(), default=dict),
        sa.Column('created_at', sa.DateTime(), default=sa.func.now()),
    )
    op.create_index('ix_events_job_type', 'events', ['job_id', 'event_type'])
    op.create_index('ix_events_created', 'events', ['created_at'])
    
    # ToolCall table
    op.create_table(
        'tool_calls',
        sa.Column('id', sa.UUID(as_uuid=True), primary_key=True),
        sa.Column('job_id', sa.UUID(as_uuid=True), sa.ForeignKey('jobs.id')),
        sa.Column('tool_name', sa.String(), nullable=False),
        sa.Column('input_hash', sa.String(), nullable=False),
        sa.Column('input_preview', sa.Text(), nullable=False),
        sa.Column('output_hash', sa.String(), nullable=False),
        sa.Column('output_preview', sa.Text(), nullable=False),
        sa.Column('latency_ms', sa.Float(), nullable=False),
        sa.Column('attempt_number', sa.Integer(), default=1),
        sa.Column('accepted', sa.Boolean(), default=True),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('called_by_agent', sa.String(), nullable=False),
        sa.Column('error_type', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), default=sa.func.now()),
    )
    op.create_index('ix_tool_calls_job', 'tool_calls', ['job_id'])
    op.create_index('ix_tool_calls_tool', 'tool_calls', ['tool_name'])
    
    # CritiqueLog table
    op.create_table(
        'critique_logs',
        sa.Column('id', sa.UUID(as_uuid=True), primary_key=True),
        sa.Column('job_id', sa.UUID(as_uuid=True), sa.ForeignKey('jobs.id')),
        sa.Column('span_start', sa.Integer(), nullable=False),
        sa.Column('span_end', sa.Integer(), nullable=False),
        sa.Column('claim', sa.Text(), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('flagged', sa.Boolean(), default=False),
        sa.Column('reasoning', sa.Text(), nullable=False),
        sa.Column('source_agent', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), default=sa.func.now()),
    )
    op.create_index('ix_critique_job', 'critique_logs', ['job_id'])
    
    # PolicyViolationLog table
    op.create_table(
        'policy_violations',
        sa.Column('id', sa.UUID(as_uuid=True), primary_key=True),
        sa.Column('job_id', sa.UUID(as_uuid=True), sa.ForeignKey('jobs.id')),
        sa.Column('violation_type', sa.String(), nullable=False),
        sa.Column('severity', sa.String(), nullable=False),
        sa.Column('agent_name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('context', sa.JSON(), default=dict),
        sa.Column('created_at', sa.DateTime(), default=sa.func.now()),
    )
    op.create_index('ix_violations_job', 'policy_violations', ['job_id'])
    op.create_index('ix_violations_severity', 'policy_violations', ['severity'])
    
    # EvalRun table
    op.create_table(
        'eval_runs',
        sa.Column('id', sa.UUID(as_uuid=True), primary_key=True),
        sa.Column('test_case_id', sa.String(), nullable=False),
        sa.Column('group', sa.String(), nullable=False),
        sa.Column('prompts_used', sa.JSON(), nullable=False),
        sa.Column('tool_calls_made', sa.JSON(), nullable=False),
        sa.Column('outputs_received', sa.JSON(), nullable=False),
        sa.Column('score_answer_correctness', sa.Float(), nullable=False),
        sa.Column('score_citation_accuracy', sa.Float(), nullable=False),
        sa.Column('score_contradiction_resolution', sa.Float(), nullable=False),
        sa.Column('score_tool_efficiency', sa.Float(), nullable=False),
        sa.Column('score_budget_compliance', sa.Float(), nullable=False),
        sa.Column('score_critique_agreement', sa.Float(), nullable=False),
        sa.Column('justification_correctness', sa.Text(), nullable=False),
        sa.Column('justification_citation', sa.Text(), nullable=False),
        sa.Column('justification_contradiction', sa.Text(), nullable=False),
        sa.Column('justification_efficiency', sa.Text(), nullable=False),
        sa.Column('justification_budget', sa.Text(), nullable=False),
        sa.Column('justification_critique', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), default=sa.func.now()),
    )
    op.create_index('ix_eval_runs_group', 'eval_runs', ['group'])
    op.create_index('ix_eval_runs_test_case', 'eval_runs', ['test_case_id'])
    
    # PromptProposal table
    op.create_table(
        'prompt_proposals',
        sa.Column('id', sa.UUID(as_uuid=True), primary_key=True),
        sa.Column('prompt_id', sa.String(), nullable=False),
        sa.Column('original_prompt', sa.Text(), nullable=False),
        sa.Column('rewritten_prompt', sa.Text(), nullable=False),
        sa.Column('unified_diff', sa.Text(), nullable=False),
        sa.Column('justification', sa.Text(), nullable=False),
        sa.Column('target_dimension', sa.String(), nullable=False),
        sa.Column('expected_improvement', sa.Float(), nullable=False),
        sa.Column('decision', sa.String(), nullable=True),
        sa.Column('reviewer_notes', sa.Text(), nullable=True),
        sa.Column('decided_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), default=sa.func.now()),
    )
    op.create_index('ix_proposals_decision', 'prompt_proposals', ['decision'])
    op.create_index('ix_proposals_created', 'prompt_proposals', ['created_at'])
    
    # EvalDelta table
    op.create_table(
        'eval_deltas',
        sa.Column('id', sa.UUID(as_uuid=True), primary_key=True),
        sa.Column('proposal_id', sa.UUID(as_uuid=True), sa.ForeignKey('prompt_proposals.id')),
        sa.Column('test_case_id', sa.String(), nullable=False),
        sa.Column('delta_correctness', sa.Float(), nullable=False),
        sa.Column('delta_citation', sa.Float(), nullable=False),
        sa.Column('delta_contradiction', sa.Float(), nullable=False),
        sa.Column('delta_efficiency', sa.Float(), nullable=False),
        sa.Column('delta_budget', sa.Float(), nullable=False),
        sa.Column('delta_critique', sa.Float(), nullable=False),
        sa.Column('improvement_ratio', sa.Float(), nullable=False),
        sa.Column('created_at', sa.DateTime(), default=sa.func.now()),
    )
    op.create_index('ix_deltas_proposal', 'eval_deltas', ['proposal_id'])


def downgrade() -> None:
    """Drop all tables."""
    op.drop_table('eval_deltas')
    op.drop_table('prompt_proposals')
    op.drop_table('eval_runs')
    op.drop_table('policy_violations')
    op.drop_table('critique_logs')
    op.drop_table('tool_calls')
    op.drop_table('events')
    op.drop_table('jobs')
