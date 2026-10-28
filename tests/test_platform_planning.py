"""Planning fixtures exercise orchestration, not model teaching quality."""
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from server.lessons.contracts import AssessmentPair, CurriculumHeader, CurriculumPlan, ObjectiveBatch
from server.lessons.planning import batches, evidence_for, focused_blueprint, prepare_plan
from server.providers.base import GenerationError


def source_fixture(count=12):
    packets = [{'id': 'source-version', 'evidence': [
        {'id': f'section-{i}', 'text': f'Original section {i}: ' + 'evidence ' * 1500,
         'location': f'Page {i + 1}', 'method': 'typed', 'uncertainty': []} for i in range(count)]}]
    inventory = [{'source_version_id': 'source-version', 'block_id': f'section-{i}',
        'summary': f'Complete audited section {i}', 'concepts': [f'concept-{i}'], 'critical_issues': []} for i in range(count)]
    return inventory, packets


class FixtureAuthor:
    settings = SimpleNamespace(text_model='fixture-author', verifier_model='fixture-verifier')

    def __init__(self, *, change=None, exclude=False, fail_at=None):
        self.calls, self.saved = [], {}
        self.change, self.exclude, self.fail_at = change, exclude, fail_at

    def ask(self, stage, model, contract, task, data):
        if stage in self.saved:
            return self.saved[stage]
        if stage == self.fail_at:
            raise GenerationError('FIXTURE_OUTAGE', 'Controlled fixture outage')
        self.calls.append((stage, data))
        if contract is CurriculumHeader:
            result = contract(title='Fixture chapter', scope='Explain every selected fixture concept.', notation={'i': 'Zero-based index'}, prerequisites=[])
        elif contract is ObjectiveBatch:
            objectives, exclusions = [], []
            for i, section in enumerate(data['sections']):
                ref = {key: section[key] for key in ('source_version_id', 'block_id')}
                if self.exclude and i == len(data['sections']) - 1:
                    exclusions.append(ref | {'reason': 'Outside the explicitly requested fixture goal.'})
                    continue
                prior = data['previous_objectives'][-1]['id'] if data['previous_objectives'] else None
                objectives.append({'id': f'local-{i}', 'title': section['concepts'][0],
                    'description': 'Explain this complete fixture concept.', 'prerequisites': [f'local-{i-1}'] if i else ([prior] if prior else []),
                    'evidence': [ref], 'worked_example': 'Use the same fixed list [2, 3] and index i.', 'visual_approach': 'A faithful bounded code trace'})
            if self.change:
                self.change(objectives, exclusions)
            result = contract(objectives=objectives, excluded=exclusions)
        elif contract is AssessmentPair:
            obj = data['fixed_curriculum']['objective']
            result = contract(assessments=[{'objective_id': obj['id'], 'variant': variant,
                'question': {'kind': 'trace', 'prompt': 'Predict this controlled fixture output.', 'starter_code': 'print(1)'},
                'key': {'expected_output': '5', 'hints': ['Follow the fixed values.'],
                    'explanation': 'The two fixed values sum to five.'}} for variant in ('base', 'equivalent')])
        else:
            result = contract(summary='Compact fixture inventory used only for shared notation.', concepts=['Python fixture concepts'])
        self.saved[stage] = result
        return result


def test_long_source_plans_and_assesses_in_bounded_batches_without_dropping_sections():
    inventory, packets = source_fixture(30)
    author = FixtureAuthor()
    plan = prepare_plan(author, inventory, packets, 'Teach every selected concept in full.')
    assert len(plan.objectives) == 30 and len(plan.assessments) == 60
    assert plan.planning_batches == 8 and len(plan.source_coverage) == 30
    assert plan.objectives[4].prerequisites == [plan.objectives[3].id]
    assert len({x.id for x in plan.objectives}) == 30
    for stage, data in author.calls:
        if stage.startswith('assessment_'):
            assert len(data['original_evidence']) == 1
            assert len(data['original_evidence'][0]['evidence']) == 1
            assert 'source_coverage' not in data['fixed_curriculum']
    public = plan.public_blueprint()
    assert 'assessments' not in public and 'reference_solution' not in str(public)


def test_completed_batches_are_reused_after_a_later_model_outage():
    inventory, packets = source_fixture()
    author = FixtureAuthor(fail_at='assessment_b2-o2')
    with pytest.raises(GenerationError, match='outage'):
        prepare_plan(author, inventory, packets, 'Explain the complete fixture chapter.')
    before = list(author.calls)
    author.fail_at = None
    plan = prepare_plan(author, inventory, packets, 'Explain the complete fixture chapter.')
    assert len(plan.objectives) == 12
    assert [stage for stage, _ in author.calls].count('objective_batch_1') == 1
    assert author.calls[:len(before)] == before


@pytest.mark.parametrize('change,code', [
    (lambda objs, exc: objs.pop(), 'INCOMPLETE_SOURCE_COVERAGE'),
    (lambda objs, exc: objs[0]['evidence'][0].update(block_id='invented'), 'INVALID_EVIDENCE'),
    (lambda objs, exc: objs[0].update(prerequisites=['future-objective']), 'INVALID_CURRICULUM_BATCH'),
    (lambda objs, exc: exc.append(objs[0]['evidence'][0] | {'reason': 'Contradicts included coverage.'}), 'INCOMPLETE_SOURCE_COVERAGE'),
])
def test_batch_cannot_omit_sections_invent_evidence_or_rewrite_prerequisites(change, code):
    inventory, packets = source_fixture(4)
    with pytest.raises(GenerationError) as failure:
        prepare_plan(FixtureAuthor(change=change), inventory, packets, 'Explain all fixture concepts.')
    assert failure.value.code == code


def test_out_of_scope_sections_have_visible_explicit_reasons():
    inventory, packets = source_fixture(4)
    plan = prepare_plan(FixtureAuthor(exclude=True), inventory, packets, 'Explain the selected fixture subset.')
    assert len(plan.objectives) == 3
    excluded = [x for x in plan.source_coverage if x.exclusion_reason]
    assert len(excluded) == 1 and excluded[0].block_id == 'section-3'
    assert not excluded[0].objective_ids
    invalid = plan.model_dump()
    invalid['source_coverage'][0]['objective_ids'] = ['nonexistent']
    with pytest.raises(ValidationError, match='match objective evidence'):
        CurriculumPlan.model_validate(invalid)


def test_focused_context_preserves_prerequisite_examples_and_original_source():
    inventory, packets = source_fixture(12)
    plan = prepare_plan(FixtureAuthor(), inventory, packets, 'Explain the full fixture chapter.')
    blueprint = plan.public_blueprint()
    obj = blueprint['objectives'][5]
    context = focused_blueprint(blueprint, obj)
    assert context['notation'] == blueprint['notation']
    assert len(context['prerequisite_context']) == 1 and len(context['prerequisite_graph']) == 5
    assert context['previous_example']['id'] == blueprint['objectives'][4]['id']
    selected = evidence_for(packets, obj)
    assert selected[0]['evidence'][0]['text'] == packets[0]['evidence'][5]['text']


def test_large_inventory_reduction_never_substitutes_for_original_section_coverage():
    inventory, packets = source_fixture(20)
    for row in inventory:
        row['summary'] += ' details' * 300
    author = FixtureAuthor()
    plan = prepare_plan(author, inventory, packets, 'Explain the full fixture chapter.')
    assert any(stage.startswith('inventory_') for stage, _ in author.calls)
    assert len(plan.source_coverage) == 20


def test_oversized_single_inventory_unit_fails_explicitly():
    with pytest.raises(GenerationError, match='nothing was omitted'):
        list(batches([{'summary': 'x' * 25000}]))
