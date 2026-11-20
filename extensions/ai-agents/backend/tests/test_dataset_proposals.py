import ast
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from text_to_bi.superset_ai_agent.modules.agent_ladder.exceptions import (
    DatasetProposalNotFoundError,
    ProposalAlreadyReviewedError,
)

SOURCE = Path(__file__).parents[1] / 'src/text_to_bi/superset_ai_agent/modules/agent_ladder/services/proposals.py'


def service(**bindings):
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    declaration = next(node for node in tree.body if isinstance(node, ast.ClassDef))
    module = ast.Module(
        body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), declaration],
        type_ignores=[],
    )
    namespace = {
        'datetime': datetime, 'timezone': timezone, 'DatasetProposalNotFoundError': DatasetProposalNotFoundError,
        'ProposalAlreadyReviewedError': ProposalAlreadyReviewedError, **bindings,
    }
    exec(compile(ast.fix_missing_locations(module), str(SOURCE), 'exec'), namespace)  # noqa: S102
    return namespace['DatasetProposalService']()


def proposal(**fields):
    return SimpleNamespace(
        id=17, name='proposed', label='Proposed', description=None, sql='SELECT id FROM base', metric={},
        question='Question', status='pending', proposer_id=2, **fields,
    )


def test_create_forwards_original_author_and_stable_retry_key():
    saved = proposal()
    calls = []
    repository = SimpleNamespace(read_for_update=lambda _: saved)
    workflow = service(expert=None, dataset_proposal_repository=lambda: repository,
                       create_dataset_draft=lambda body, cookie, csrf: calls.append((body, cookie, csrf)) or 44)
    assert workflow.create(17, 3, 'session', 'csrf') is saved
    assert saved.status == 'created' and saved.dataset_id == 44 and saved.reviewer_id == 3
    assert calls[0][0]['creation_key'] == 'ai-agent:dataset-proposal:17'
    assert calls[0][0]['proposer_id'] == 2
    assert calls[0][1:] == ('session', 'csrf')


def test_http_failure_keeps_proposal_pending():
    saved = proposal()

    def fail(*_):
        raise ConnectionError('disconnected')

    workflow = service(
        dataset_proposal_repository=lambda: SimpleNamespace(read_for_update=lambda _: saved), create_dataset_draft=fail,
    )
    with pytest.raises(ConnectionError):
        workflow.create(17, 3, 'session', 'csrf')
    assert saved.status == 'pending'
    assert not hasattr(saved, 'dataset_id')


@pytest.mark.parametrize(
    'saved, error',
    [(None, DatasetProposalNotFoundError), (SimpleNamespace(status='created'), ProposalAlreadyReviewedError)],
)
def test_review_requires_existing_pending_proposal(saved, error):
    workflow = service(dataset_proposal_repository=lambda: SimpleNamespace(read_for_update=lambda _: saved))
    with pytest.raises(error):
        workflow.require_pending(17)


def test_duplicate_sql_reuses_pending_proposal():
    saved = proposal()
    repository = SimpleNamespace(pending_with_fingerprint=lambda _: saved)
    workflow = service(
        dataset_proposal_repository=lambda: repository, validate_dataset_draft=lambda *_: {'sql_fingerprint': 'same'},
    )
    assert workflow.propose({}, 2, 'session', 'csrf') == (saved, False)


def test_update_keeps_original_question():
    saved = proposal()
    calls = []
    workflow = service(dataset_proposal_repository=lambda: SimpleNamespace(read_for_update=lambda _: saved),
                       validate_dataset_draft=lambda body, *_: calls.append(body) or {'label': 'Updated'})
    workflow.update(17, {'label': 'Updated', 'question': 'Replacement'}, 'session', 'csrf')
    assert calls[0]['question'] == 'Question'
    assert saved.label == 'Updated'
