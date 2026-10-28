"""Resumable, bounded curriculum construction without dropping source sections.

Summaries set shared scope/notation only. Every original audited section is still
planned individually and accounted for in the final source-coverage ledger.
"""
import json

from pydantic import Field

from server.lessons.contracts import (AssessmentPair, Contract, CurriculumHeader,
    CurriculumPlan, ObjectiveBatch, SourceCoverage)
from server.providers.base import GenerationError


class InventorySummary(Contract):
    summary: str = Field(min_length=10, max_length=2000)
    concepts: list[str] = Field(min_length=1, max_length=20)


def encoded_size(value):
    return len(json.dumps(value, ensure_ascii=False))


def batches(items, *, limit=24000, count=4):
    group = []
    for item in items:
        if encoded_size([item]) > limit:
            raise GenerationError("GENERATION_BATCH_REQUIRED", "One source inventory unit exceeds the planning budget. Split that evidence block; nothing was omitted.")
        if group and (len(group) >= count or encoded_size([*group, item]) > limit):
            yield group
            group = []
        group.append(item)
    if group:
        yield group


def evidence_for(packets, objective):
    refs = {(x['source_version_id'], x['block_id']) for x in objective['evidence']}
    selected = [{"id": packet['id'], "evidence": [block for block in packet['evidence']
        if (packet['id'], block['id']) in refs]} for packet in packets]
    selected = [packet for packet in selected if packet['evidence']]
    if {(p['id'], b['id']) for p in selected for b in p['evidence']} != refs:
        raise GenerationError("INVALID_EVIDENCE", "An objective references a missing original source section.")
    return selected


def focused_blueprint(blueprint, objective):
    """Retain the fixed objective and its prerequisite/example continuity.

    The entire curriculum remains persisted. Unrelated evidence, assessments and
    worked examples must not consume each block's model context.
    """
    by_id = {x['id']: x for x in blueprint['objectives']}
    needed, pending = set(), list(objective['prerequisites'])
    while pending:
        identifier = pending.pop()
        if identifier in needed:
            continue
        needed.add(identifier)
        pending.extend(by_id[identifier]['prerequisites'])
    index = next(i for i, x in enumerate(blueprint['objectives']) if x['id'] == objective['id'])
    previous = blueprint['objectives'][index - 1] if index else None
    return {key: blueprint[key] for key in ('title', 'scope', 'prerequisites', 'notation')} | {
        'objective': objective,
        'prerequisite_graph': [{key: x[key] for key in ('id', 'title', 'prerequisites')}
            for x in blueprint['objectives'] if x['id'] in needed],
        'prerequisite_context': [{key: x[key] for key in ('id', 'title', 'description', 'worked_example')}
            for x in blueprint['objectives'] if x['id'] in objective['prerequisites']],
        'previous_example': {key: previous[key] for key in ('id', 'title', 'worked_example')} if previous else None,
    }


def prepare_plan(author, inventory, packets, goal, *, batch_limit=24000):
    if not inventory:
        raise GenerationError("EMPTY_SOURCE", "A lesson requires at least one audited source section.")
    refs = [(x['source_version_id'], x['block_id']) for x in inventory]
    original_refs = [(p['id'], block['id']) for p in packets for block in p['evidence']]
    if len(set(refs)) != len(refs) or len(set(original_refs)) != len(original_refs) or set(refs) != set(original_refs):
        raise GenerationError("INVALID_EVIDENCE", "The audited inventory must match every original source section exactly once.")
    overview = inventory
    # These resumable reductions do not remove anything from the original ledger.
    for level in range(8):
        if encoded_size(overview) <= 32000:
            break
        reduced = []
        for number, group in enumerate(batches(overview), 1):
            summary = author.ask(f'inventory_{level}_{number}', author.settings.text_model, InventorySummary,
                'Summarize these audited sections for shared lesson scope and notation only. This summary is not permission to omit source sections.',
                {'goal': goal, 'sections': group})
            reduced.append(summary.model_dump())
        if encoded_size(reduced) >= encoded_size(overview):
            raise GenerationError("GENERATION_BATCH_REQUIRED", "The scope overview did not fit a bounded summary. Split the requested lesson into explicit parts; no sections were discarded.")
        overview = reduced
    else:
        raise GenerationError("GENERATION_BATCH_REQUIRED", "The source needs a course-level scope decision before further planning.")
    header = author.ask('curriculum_scope', author.settings.text_model, CurriculumHeader,
        'Set a shared sourced scope, prerequisites and consistent notation for this learning goal. This is not the objective plan. '
        'Every original source section will be planned in subsequent batches. Do not impose a lesson duration or scene cap.',
        {'goal': goal, 'source_overview': overview})
    objectives, coverage = [], []
    groups = list(batches(inventory, limit=batch_limit))
    for number, group in enumerate(groups, 1):
        previous = [{key: obj[key] for key in ('id', 'title', 'prerequisites')} for obj in objectives]
        batch = author.ask(f'objective_batch_{number}', author.settings.text_model, ObjectiveBatch,
            'Plan complete, topologically ordered objectives for these exact audited source sections within the fixed shared scope. '
            'Plan only objectives that serve the learner goal, usually 3 to 6 for one topic, each distinct (no overlapping duplicates); '
            'earlier objectives must be listed as prerequisites of later ones that build on them. '
            'Set check_kind for every objective, and use at least two different kinds across the lesson; include python whenever an objective '
            'is about writing code. '
            'Each section must be referenced by an objective or explicitly excluded with a substantive reason visible to the author. '
            'Preserve every teachable concept in scope. Use small coherent objectives with bounded relevant evidence. '
            'Use local IDs for new objectives; prerequisites may reference earlier local IDs or exact IDs of previous objectives. '
            'Do not repeat prior objectives. Keep notation and worked-example values consistent across batches.',
            {'goal': goal, 'shared_scope': header.model_dump(), 'sections': group, 'previous_objectives': previous})
        current_refs = {(x['source_version_id'], x['block_id']) for x in group}
        # Namespace generated local IDs deterministically; duplicate IDs cannot
        # collide across batches or erase an earlier objective.
        local_ids = [x.id for x in batch.objectives]
        if len(local_ids) != len(set(local_ids)) or set(local_ids).intersection(x['id'] for x in objectives):
            raise GenerationError("INVALID_CURRICULUM_BATCH", "A planning batch reused an objective ID. Retry or review the scope.")
        remap = {identifier: f'b{number}-o{index}' for index, identifier in enumerate(local_ids, 1)}
        known = {x['id'] for x in objectives}
        usage = {}
        for value in batch.objectives:
            obj = value.model_dump()
            obj['id'] = remap[obj['id']]
            obj['prerequisites'] = [remap.get(x, x) for x in obj['prerequisites']]
            if not set(obj['prerequisites']).issubset(known):
                raise GenerationError("INVALID_CURRICULUM_BATCH", "A prerequisite is missing, cyclic or ordered after its dependent objective.")
            for ref in obj['evidence']:
                key = (ref['source_version_id'], ref['block_id'])
                if key not in current_refs:
                    raise GenerationError("INVALID_EVIDENCE", "A planning batch referenced a section outside its exact source scope.")
                usage.setdefault(key, []).append(obj['id'])
            objectives.append(obj)
            known.add(obj['id'])
        exclusions = {(x.source_version_id, x.block_id): x.reason for x in batch.excluded}
        if getattr(author.settings, "local", False):
            # A small local planner often forgets to account for a section; record it as
            # an explicit, visible exclusion instead of failing the whole lesson.
            for key in current_refs - set(usage) - set(exclusions):
                exclusions[key] = "Not used by the planner for this learning goal (recorded automatically)."
            for key in set(exclusions) & set(usage):
                del exclusions[key]
        if ((len(exclusions) != len(batch.excluded) and not getattr(author.settings, "local", False)) or set(exclusions).intersection(usage)
                or set(usage) | set(exclusions) != current_refs):
            raise GenerationError("INCOMPLETE_SOURCE_COVERAGE", "Every selected source section must be included or explicitly excluded exactly once. No incomplete curriculum was created.")
        coverage.extend(SourceCoverage(source_version_id=source, block_id=block,
            objective_ids=sorted(set(usage.get((source, block), []))), exclusion_reason=exclusions.get((source, block), '')).model_dump()
            for source, block in sorted(current_refs))
    if not objectives:
        raise GenerationError("SOURCE_OUTSIDE_SCOPE", "All selected sections were excluded. Choose a supported goal or provide relevant material.")
    blueprint = header.model_dump() | {'objectives': objectives, 'source_coverage': coverage, 'planning_batches': len(groups)}
    from server.lessons.authoring import QUESTION_STYLE  # authoring imports this module
    assessments = []
    for obj in objectives:
        ask = lambda stage, task: author.ask(stage, author.settings.text_model, AssessmentPair,
            task + 'Create exactly one base and one fresh equivalent checkpoint for the fixed objective. Do not change its ID, scope or prerequisites. '
            'Choose the question kind that best tests this objective, and use the same kind for both variants: '
            'mcq (one correct option, 3-5 options, plausible distractors mapped in misconception_map) for recognising concepts; '
            'multiple (several correct options) for properties/classification; trace (predict the exact printed output) for reading code; '
            'python (write a Python 3 stdin/stdout program; reference and all solutions must be Python 3, the only language the grader runs) '
            'only when the objective is about implementing code; if the material teaches another language, use trace or short instead; '
            'short (1-4 sentence written answer with model_answer and 2-5 rubric points) for definitions, reasoning, comparisons and why-questions. '
            'Do not default to mcq: pick what a good teacher would ask. '
            'For mcq/multiple, give each option a short id like "a", "b", "c" and list those ids (not the option text) in key.correct. '
            'For Python provide stdin/stdout tests, essential cases, reference and alternative correct solutions and at least two known wrong solutions. '
            'Every solution must be a complete executable program with an input-reading and output-printing entry point, '
            'even when it also defines a function. stdin contains only plain input data, never Python calls or assertions; '
            'there is no injected function-test harness. State the same input/output format in the prompt and public examples. '
            'Keep hints and all grading rules in the private key. Questions must be solvable from original evidence and prerequisites. ' + QUESTION_STYLE,
            {'fixed_curriculum': focused_blueprint(blueprint, obj), 'original_evidence': evidence_for(packets, obj)})
        kind = obj.get('check_kind', 'mcq')
        try:
            pair = ask(f"assessment_{obj['id']}", f'Use kind "{kind}" for both variants (chosen when the objective was planned). ')
        except GenerationError as error:
            if error.code != "CONTENT_NEEDS_REVIEW" or not getattr(author.settings, "local", False):
                raise
            # A small local model can fail a complex key repeatedly; a written-answer
            # check with a rubric is the simplest valid form for any objective. The
            # objective's own kind is updated too, or the model keeps following it.
            obj['check_kind'] = 'short'
            pair = ask(f"assessment_{obj['id']}_short", 'Use kind "short" for both variants, with model_answer and 2-4 rubric points. ')
        if any(item.objective_id != obj['id'] for item in pair.assessments):
            raise GenerationError("INVALID_ASSESSMENT_SCOPE", "An assessment changed its fixed objective. No curriculum was created.")
        assessments.extend(item.model_dump() for item in pair.assessments)
    return CurriculumPlan.model_validate(blueprint | {'assessments': assessments})
