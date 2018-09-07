# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import copy
import logging
import six

from orquesta import events
from orquesta import exceptions as exc
from orquesta.expressions import base as expr
from orquesta import graphing
from orquesta.specs import base as specs
from orquesta.specs import loader as specs_loader
from orquesta import states
from orquesta.states import machines
from orquesta.utils import context as ctx
from orquesta.utils import dictionary as dx
from orquesta.utils import plugin


LOG = logging.getLogger(__name__)


class TaskFlow(object):

    def __init__(self):
        self.tasks = dict()
        self.sequence = list()
        self.contexts = list()
        self.staged = dict()

    def serialize(self):
        return {
            'tasks': copy.deepcopy(self.tasks),
            'sequence': copy.deepcopy(self.sequence),
            'contexts': copy.deepcopy(self.contexts),
            'staged': copy.deepcopy(self.staged)
        }

    @classmethod
    def deserialize(cls, data):
        instance = cls()
        instance.tasks = copy.deepcopy(data.get('tasks', dict()))
        instance.sequence = copy.deepcopy(data.get('sequence', list()))
        instance.contexts = copy.deepcopy(data.get('contexts', list()))
        instance.staged = copy.deepcopy(data.get('staged', dict()))

        return instance

    def get_tasks_by_state(self, states):
        return [t for t in self.sequence if t['state'] in states]

    @property
    def has_active_tasks(self):
        return len(self.get_tasks_by_state(states.ACTIVE_STATES)) > 0

    @property
    def has_pausing_tasks(self):
        return len(self.get_tasks_by_state([states.PAUSING])) > 0

    @property
    def has_paused_tasks(self):
        return len(self.get_tasks_by_state([states.PAUSED, states.PENDING])) > 0

    @property
    def has_canceling_tasks(self):
        return len(self.get_tasks_by_state([states.CANCELING])) > 0

    @property
    def has_canceled_tasks(self):
        return len(self.get_tasks_by_state([states.CANCELED])) > 0

    def get_staged_tasks(self):
        return [k for k, v in six.iteritems(self.staged) if v.get('ready', True) is True]

    @property
    def has_staged_tasks(self):
        return len(self.get_staged_tasks()) > 0


class WorkflowConductor(object):

    def __init__(self, spec, context=None, inputs=None):
        if not spec or not isinstance(spec, specs.Spec):
            raise ValueError('The value of "spec" is not type of Spec.')

        self.spec = spec
        self.catalog = self.spec.get_catalog()
        self.spec_module = specs_loader.get_spec_module(self.catalog)
        self.composer = plugin.get_module('orquesta.composers', self.catalog)

        self._workflow_state = states.UNSET
        self._graph = None
        self._flow = None
        self._parent_ctx = context or {}
        self._inputs = inputs or {}
        self._outputs = None
        self._errors = []

    def restore(self, graph, state=None, errors=None, flow=None,
                inputs=None, outputs=None, context=None):
        if not graph or not isinstance(graph, graphing.WorkflowGraph):
            raise ValueError('The value of "graph" is not type of WorkflowGraph.')

        if not flow or not isinstance(flow, TaskFlow):
            raise ValueError('The value of "flow" is not type of TaskFlow.')

        if state and not states.is_valid(state):
            raise exc.InvalidState(state)

        if inputs is not None and not isinstance(inputs, dict):
            raise ValueError('The value of "inputs" is not type of dict.')

        if outputs is not None and not isinstance(outputs, dict):
            raise ValueError('The value of "outputs" is not type of dict.')

        self._workflow_state = state
        self._graph = graph
        self._flow = flow
        self._parent_ctx = context or {}
        self._inputs = inputs or {}
        self._outputs = outputs
        self._errors = errors or []

    def serialize(self):
        return {
            'spec': self.spec.serialize(),
            'graph': self.graph.serialize(),
            'flow': self.flow.serialize(),
            'context': self.get_workflow_parent_context(),
            'input': self.get_workflow_input(),
            'output': self.get_workflow_output(),
            'errors': copy.deepcopy(self.errors),
            'state': self.get_workflow_state()
        }

    @classmethod
    def deserialize(cls, data):
        spec_module = specs_loader.get_spec_module(data['spec']['catalog'])
        spec = spec_module.WorkflowSpec.deserialize(data['spec'])

        graph = graphing.WorkflowGraph.deserialize(data['graph'])
        state = data['state']
        flow = TaskFlow.deserialize(data['flow'])
        context = copy.deepcopy(data['context'])
        inputs = copy.deepcopy(data['input'])
        outputs = copy.deepcopy(data['output'])
        errors = copy.deepcopy(data['errors'])

        instance = cls(spec)
        instance.restore(graph, state, errors, flow, inputs, outputs, context)

        return instance

    @property
    def graph(self):
        if not self._graph:
            self._graph = self.composer.compose(self.spec)

        return self._graph

    @property
    def flow(self):
        if not self._flow:
            self._flow = TaskFlow()

            # Render runtime and default workflow inputs.
            rendered_inputs, input_errors = self.spec.render_input(self.get_workflow_input())
            rendered_vars, var_errors = self.spec.render_vars(rendered_inputs)
            errors = input_errors + var_errors

            if errors:
                self.log_errors(errors)
                self.request_workflow_state(states.FAILED)

            # Proceed if there is no issue with rendering of inputs and vars.
            if self.get_workflow_state() not in states.ABENDED_STATES:
                # Set the initial workflow context.
                init_ctx = dict(list(rendered_inputs.items()) + list(rendered_vars.items()))
                init_ctx = dx.merge_dicts(init_ctx, self.get_workflow_parent_context(), True)
                self._flow.contexts.append({'srcs': [], 'value': init_ctx})

                # Identify the starting tasks and set the pointer to the initial context entry.
                for task_node in self.graph.roots:
                    self._flow.staged[task_node['id']] = {'ctxs': [0], 'ready': True}

        return self._flow

    @property
    def errors(self):
        return self._errors

    def log_error(self, error, task_id=None, task_transition_id=None):
        entry = {'message': error}

        if task_id:
            entry['task_id'] = task_id

        if task_transition_id:
            entry['task_transition_id'] = task_transition_id

        self.errors.append(entry)

    def log_errors(self, errors, task_id=None, task_transition_id=None):
        for error in errors:
            self.log_error(error, task_id=task_id, task_transition_id=task_transition_id)

    def get_workflow_parent_context(self):
        return copy.deepcopy(self._parent_ctx)

    def get_workflow_input(self):
        return copy.deepcopy(self._inputs)

    def get_workflow_state(self):
        return self._workflow_state

    def _set_workflow_state(self, value):
        if not machines.WorkflowStateMachine.is_transition_valid(self._workflow_state, value):
            raise exc.InvalidStateTransition(self._workflow_state, value)

        self._workflow_state = value

    def request_workflow_state(self, state):
        # Record current workflow state.
        current_state = self.get_workflow_state()

        # Process state change event.
        wf_ex_event = events.WorkflowExecutionEvent(state)
        machines.WorkflowStateMachine.process_event(self, wf_ex_event)

        # Get workflow state after event is processed.
        updated_state = self.get_workflow_state()

        # If state has not changed as expected, then raise exception.
        if state != current_state and current_state == updated_state:
            raise exc.InvalidWorkflowStateTransition(current_state, wf_ex_event.name)

    def get_workflow_initial_context(self):
        return copy.deepcopy(self.flow.contexts[0])

    def get_workflow_terminal_context_idx(self):
        query = filter(lambda x: 'term' in x[1] and x[1]['term'], enumerate(self.flow.contexts))
        match = list(query)

        if not match or len(match) <= 0:
            return None

        if match and len(match) != 1:
            raise exc.WorkflowContextError('More than one final workflow context found.')

        return match[0][0]

    def get_workflow_terminal_context(self):
        if self.get_workflow_state() not in states.COMPLETED_STATES:
            raise exc.WorkflowContextError('Workflow is not in completed state.')

        term_ctx_idx = self.get_workflow_terminal_context_idx()

        if not term_ctx_idx:
            raise exc.WorkflowContextError('Unable to determine the final workflow context.')

        return copy.deepcopy(self.flow.contexts[term_ctx_idx])

    def update_workflow_terminal_context(self, ctx_diff, task_flow_idx):
        term_ctx_idx = self.get_workflow_terminal_context_idx()

        if not term_ctx_idx:
            term_ctx_val = copy.deepcopy(ctx_diff)
            term_ctx_entry = {'src': [task_flow_idx], 'term': True, 'value': term_ctx_val}
            self.flow.contexts.append(term_ctx_entry)
            term_ctx_idx = len(self.flow.contexts) - 1
        else:
            term_ctx_entry = self.flow.contexts[term_ctx_idx]
            if task_flow_idx not in term_ctx_entry['src']:
                term_ctx_val = dx.merge_dicts(term_ctx_entry['value'], ctx_diff, True)
                term_ctx_entry['src'].append(task_flow_idx)
                term_ctx_entry['value'] = term_ctx_val

    def render_workflow_outputs(self):
        # Render workflow outputs if workflow succeeded.
        if self.get_workflow_state() == states.SUCCEEDED and not self._outputs:
            outputs, errors = self.spec.render_output(self.get_workflow_terminal_context()['value'])

            if errors:
                self.log_errors(errors)
                self.request_workflow_state(states.FAILED)

            # Persist outputs if there is no issue with rendering.
            if self.get_workflow_state() not in states.ABENDED_STATES and outputs:
                self._outputs = outputs

    def get_workflow_output(self):
        return copy.deepcopy(self._outputs) if self._outputs else None

    def render_task_spec(self, task_name, ctx_value):
        task_spec = self.spec.tasks.get_task(task_name).copy()
        task_spec.action = expr.evaluate(task_spec.action, ctx_value)
        task_spec.input = expr.evaluate(getattr(task_spec, 'input', {}), ctx_value)
        return task_spec

    def inbound_criteria_satisfied(self, task_id):
        inbounds = self.graph.get_prev_transitions(task_id)
        inbounds_satisfied = []
        barrier = 1

        if self.graph.has_barrier(task_id):
            barrier = self.graph.get_barrier(task_id)
            barrier = len(inbounds) if barrier == '*' else barrier

        for prev_seq in inbounds:
            prev_task_flow_entry = self.get_task_flow_entry(prev_seq[0])

            if prev_task_flow_entry:
                prev_task_transition_id = prev_seq[1] + '__' + str(prev_seq[2])

                if prev_task_flow_entry.get(prev_task_transition_id):
                    inbounds_satisfied.append(prev_task_transition_id)

        return (len(inbounds_satisfied) >= barrier)

    def get_task(self, task_id):
        task_node = self.graph.get_task(task_id)
        task_name = task_node['name']

        try:
            task_ctx = self.get_task_initial_context(task_id)['value']
        except ValueError:
            task_ctx = self.get_workflow_initial_context()

        current_task = {'id': task_id, 'name': task_name}
        task_ctx = ctx.set_current_task(task_ctx, current_task)
        task_spec = self.render_task_spec(task_name, task_ctx)

        return {
            'id': task_id,
            'name': task_name,
            'ctx': task_ctx,
            'spec': task_spec
        }

    def get_start_tasks(self):
        if self.get_workflow_state() not in states.RUNNING_STATES:
            return []

        tasks = []

        for task_node in self.graph.roots:
            try:
                tasks.append(self.get_task(task_node['id']))
            except Exception as e:
                self.log_error(str(e), task_id=task_node['id'])
                self.request_workflow_state(states.FAILED)
                continue

        # Return nothing if there is error(s) on determining start tasks.
        if self.get_workflow_state() in states.COMPLETED_STATES:
            return []

        return sorted(tasks, key=lambda x: x['name'])

    def has_next_tasks(self, task_id=None):
        next_tasks = []

        if not task_id:
            next_tasks = self.flow.get_staged_tasks()
        else:
            next_tasks = [
                t[1] for t in self.graph.get_next_transitions(task_id)
                if self.inbound_criteria_satisfied(t[1])
            ]

        return len(next_tasks) > 0

    def get_next_tasks(self, task_id=None):
        if self.get_workflow_state() not in states.RUNNING_STATES:
            return []

        next_tasks = []

        if not task_id:
            staged_tasks = [
                k for k, v in six.iteritems(self.flow.staged)
                if v.get('ready', True) is True
            ]

            for staged_task_id in staged_tasks:
                try:
                    next_tasks.append(self.get_task(staged_task_id))
                except Exception as e:
                    self.log_error(str(e), task_id=staged_task_id)
                    self.request_workflow_state(states.FAILED)
                    continue
        else:
            task_flow_entry = self.get_task_flow_entry(task_id)

            if not task_flow_entry or task_flow_entry.get('state') not in states.COMPLETED_STATES:
                return []

            outbounds = self.graph.get_next_transitions(task_id)

            for next_seq in outbounds:
                next_task_id, seq_key = next_seq[1], next_seq[2]
                task_transition_id = next_task_id + '__' + str(seq_key)

                # Evaluate if outbound criteria is satisfied.
                if not task_flow_entry.get(task_transition_id):
                    continue

                # Evaluate if inbound criteria for the next task is satisfied.
                if not self.inbound_criteria_satisfied(next_task_id):
                    continue

                next_task_node = self.graph.get_task(next_task_id)

                # If the next task is named noop which is a reserved task name, then skip the task.
                if next_task_node['name'] == 'noop':
                    continue

                try:
                    next_tasks.append(self.get_task(next_task_id))
                except Exception as e:
                    self.log_error(str(e), task_id=next_task_id)
                    self.request_workflow_state(states.FAILED)
                    continue

        # Return nothing if there is error(s) on determining next tasks.
        if self.get_workflow_state() in states.COMPLETED_STATES:
            return []

        return sorted(next_tasks, key=lambda x: x['name'])

    def get_task_flow_idx(self, task_id):
        return self.flow.tasks.get(task_id)

    def get_task_flow_entry(self, task_id):
        flow_idx = self.get_task_flow_idx(task_id)

        return self.flow.sequence[flow_idx] if flow_idx is not None else None

    def add_task_flow(self, task_id, in_ctx_idx=None):
        if not self.graph.has_task(task_id):
            raise exc.InvalidTask(task_id)

        task_flow_entry = {'id': task_id, 'ctx': in_ctx_idx}
        self.flow.sequence.append(task_flow_entry)
        self.flow.tasks[task_id] = len(self.flow.sequence) - 1

        return task_flow_entry

    def update_task_flow(self, task_id, event):
        in_ctx_idx = 0

        # Throw exception if not expected event type.
        if not issubclass(type(event), events.ExecutionEvent):
            raise TypeError('Event is not type of ExecutionEvent.')

        # Throw exception if task does not exist in the workflow graph.
        if not self.graph.has_task(task_id):
            raise exc.InvalidTask(task_id)

        # Try to get the task flow entry.
        task_flow_entry = self.get_task_flow_entry(task_id)

        # Throw exception if task is not staged and there is no task flow entry.
        if task_id not in self.flow.staged and not task_flow_entry:
            raise exc.InvalidTaskFlowEntry(task_id)

        # Remove the task from the staged list if it is processed.
        if event.state and task_id in self.flow.staged:
            in_ctx_idxs = self.flow.staged[task_id]['ctxs']

            if len(in_ctx_idxs) <= 0 or all(x == in_ctx_idxs[0] for x in in_ctx_idxs):
                in_ctx_idx = in_ctx_idxs[0]
            else:
                new_ctx_entry = self.converge_task_contexts(in_ctx_idxs)
                self.flow.contexts.append(new_ctx_entry)
                in_ctx_idx = len(self.flow.contexts) - 1

            del self.flow.staged[task_id]

        # Create new task flow entry if it does not exist.
        if not task_flow_entry:
            task_flow_entry = self.add_task_flow(task_id, in_ctx_idx=in_ctx_idx)

        # If task is already completed and in cycle, then create new task flow entry.
        if self.graph.in_cycle(task_id) and task_flow_entry.get('state') in states.COMPLETED_STATES:
            task_flow_entry = self.add_task_flow(task_id, in_ctx_idx=in_ctx_idx)

        # Process the action execution event using the task state machine and update the task state.
        machines.TaskStateMachine.process_event(task_flow_entry, event)

        # Evaluate task transitions if task is in completed state.
        if task_flow_entry['state'] in states.COMPLETED_STATES:
            # Get task details required for updating outgoing context.
            task_node = self.graph.get_task(task_id)
            task_name = task_node['name']
            task_spec = self.spec.tasks.get_task(task_name)
            task_flow_idx = self.get_task_flow_idx(task_id)

            # Set current task in the context.
            in_ctx_idx = task_flow_entry['ctx']
            in_ctx_val = self.flow.contexts[in_ctx_idx]['value']
            current_task = {'id': task_id, 'name': task_name, 'result': event.result}
            current_ctx = ctx.set_current_task(in_ctx_val, current_task)

            # Setup context for evaluating expressions in task transition criteria.
            flow_ctx = {'__flow': self.flow.serialize()}
            current_ctx = dx.merge_dicts(current_ctx, flow_ctx, True)

            # Identify task transitions for the current completed task.
            task_transitions = self.graph.get_next_transitions(task_id)

            # Update workflow context when there is no transitions.
            if not task_transitions:
                self.update_workflow_terminal_context(in_ctx_val, task_flow_idx)

            # Iterate thru each outbound task transitions.
            for task_transition in task_transitions:
                task_transition_id = task_transition[1] + '__' + str(task_transition[2])

                # Evaluate the criteria for task transition. If there is a failure while
                # evaluating expression(s), fail the workflow.
                try:
                    criteria = task_transition[3].get('criteria') or []
                    evaluated_criteria = [expr.evaluate(c, current_ctx) for c in criteria]
                    task_flow_entry[task_transition_id] = all(evaluated_criteria)
                except Exception as e:
                    self.log_error(str(e), task_id, task_transition_id)
                    self.request_workflow_state(states.FAILED)
                    continue

                # If criteria met, then mark the next task staged and calculate outgoing context.
                if task_flow_entry[task_transition_id]:
                    next_task_node = self.graph.get_task(task_transition[1])
                    next_task_name = next_task_node['name']
                    next_task_id = next_task_node['id']

                    out_ctx_val, errors = task_spec.finalize_context(
                        next_task_name,
                        criteria,
                        copy.deepcopy(current_ctx)
                    )

                    if errors:
                        self.log_errors(errors, task_id, task_transition_id)
                        self.request_workflow_state(states.FAILED)
                        continue

                    if out_ctx_val != in_ctx_val:
                        task_flow_idx = self.get_task_flow_idx(task_id)
                        self.flow.contexts.append({'srcs': [task_flow_idx], 'value': out_ctx_val})
                        out_ctx_idx = len(self.flow.contexts) - 1
                    else:
                        out_ctx_idx = in_ctx_idx

                    # Check if inbound criteria are met.
                    ready = self.inbound_criteria_satisfied(task_transition[1])

                    if (task_transition[1] in self.flow.staged and
                            'ctxs' in self.flow.staged[task_transition[1]]):
                        self.flow.staged[task_transition[1]]['ctxs'].append(out_ctx_idx)
                        self.flow.staged[task_transition[1]]['ready'] = ready
                    else:
                        staging_data = {'ctxs': [out_ctx_idx], 'ready': ready}
                        self.flow.staged[task_transition[1]] = staging_data

                    # If the next task is noop, then mark the task as completed.
                    if next_task_name == 'noop':
                        self.update_task_flow(next_task_id, events.TaskNoopEvent())

                    # If the next task is fail, then fail the workflow..
                    if next_task_name == 'fail':
                        self.update_task_flow(next_task_id, events.TaskFailEvent())

        # Process the task event using the workflow state machine and update the workflow state.
        task_ex_event = events.TaskExecutionEvent(task_id, task_flow_entry['state'])
        machines.WorkflowStateMachine.process_event(self, task_ex_event)

        # Render workflow output if workflow is completed.
        if self.get_workflow_state() in states.COMPLETED_STATES:
            in_ctx_idx = task_flow_entry['ctx']
            in_ctx_val = self.flow.contexts[in_ctx_idx]['value']
            task_flow_idx = self.get_task_flow_idx(task_id)
            self.update_workflow_terminal_context(in_ctx_val, task_flow_idx)
            self.render_workflow_outputs()

        return task_flow_entry

    def converge_task_contexts(self, ctx_idxs):
        if len(ctx_idxs) <= 0 or all(x == ctx_idxs[0] for x in ctx_idxs):
            return self.flow.contexts[ctx_idxs[0]]

        ctx_srcs = []
        merged_ctx = {}

        for i in ctx_idxs:
            ctx_entry = self.flow.contexts[i]
            merged_ctx = dx.merge_dicts(merged_ctx, copy.deepcopy(ctx_entry['value']), True)
            ctx_srcs.extend(ctx_entry['srcs'])

        return {'srcs': list(set(ctx_srcs)), 'value': merged_ctx}

    def get_task_initial_context(self, task_id):
        task_flow_entry = self.get_task_flow_entry(task_id)

        if task_flow_entry:
            in_ctx_idx = task_flow_entry.get('ctx')
            return copy.deepcopy(self.flow.contexts[in_ctx_idx])

        if task_id in self.flow.staged:
            in_ctx_idxs = self.flow.staged[task_id]['ctxs']
            return self.converge_task_contexts(in_ctx_idxs)

        raise ValueError('Unable to determine context for task "%s".' % task_id)

    def get_task_transition_contexts(self, task_id):
        contexts = {}

        task_flow_entry = self.get_task_flow_entry(task_id)

        if not task_flow_entry:
            raise exc.InvalidTaskFlowEntry(task_id)

        for t in self.graph.get_next_transitions(task_id):
            task_transition_id = t[1] + '__' + str(t[2])

            if task_transition_id in task_flow_entry and task_flow_entry[task_transition_id]:
                contexts[task_transition_id] = self.get_task_initial_context(t[1])

        return contexts
