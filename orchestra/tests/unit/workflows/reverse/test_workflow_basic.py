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

from orchestra.tests.unit import base


class BasicWorkflowConductorTest(base.WorkflowConductorTest):

    @classmethod
    def setUpClass(cls):
        cls.composer_name = 'reverse'
        super(BasicWorkflowConductorTest, cls).setUpClass()

    def test_sequential(self):
        wf_name = 'sequential'

        expected_wf_graph = {
            'directed': True,
            'graph': {},
            'nodes': [
                {
                    'id': 'task1'
                },
                {
                    'id': 'task2'
                },
                {
                    'id': 'task3'
                }
            ],
            'adjacency': [
                [
                    {
                        'id': 'task2',
                        'key': 0,
                        'criteria': self._get_seq_expr('task1')
                    }
                ],
                [
                    {
                        'id': 'task3',
                        'key': 0,
                        'criteria': self._get_seq_expr('task2')
                    }
                ],
                []
            ],
            'multigraph': True
        }

        self._assert_wf_graph(wf_name, expected_wf_graph)

        expected_wf_ex_graph = {
            'directed': True,
            'graph': {},
            'nodes': [
                {
                    'id': 'task1',
                    'name': 'task1'
                },
                {
                    'id': 'task2',
                    'name': 'task2'
                },
                {
                    'id': 'task3',
                    'name': 'task3'
                }
            ],
            'adjacency': [
                [
                    {
                        'id': 'task2',
                        'key': 0,
                        'criteria': self._get_seq_expr('task1')
                    }
                ],
                [
                    {
                        'id': 'task3',
                        'key': 0,
                        'criteria': self._get_seq_expr('task2')
                    }
                ],
                []
            ],
            'multigraph': True
        }

        self._assert_compose(wf_name, expected_wf_ex_graph)

        expected_task_seq = [
            'task1',
            'task2',
            'task3'
        ]

        self._assert_conduct(expected_wf_ex_graph, expected_task_seq)

    def test_parallel(self):
        wf_name = 'parallel'

        expected_wf_graph = {
            'directed': True,
            'graph': {},
            'nodes': [
                {
                    'id': 'task1'
                },
                {
                    'id': 'task2'
                },
                {
                    'id': 'task3'
                },
                {
                    'id': 'task4'
                },
                {
                    'id': 'task5'
                },
                {
                    'id': 'task6'
                }
            ],
            'adjacency': [
                [
                    {
                        'id': 'task2',
                        'key': 0,
                        'criteria': self._get_seq_expr('task1')
                    }
                ],
                [
                    {
                        'id': 'task3',
                        'key': 0,
                        'criteria': self._get_seq_expr('task2')
                    }
                ],
                [],
                [
                    {
                        'id': 'task5',
                        'key': 0,
                        'criteria': self._get_seq_expr('task4')
                    }
                ],
                [
                    {
                        'id': 'task6',
                        'key': 0,
                        'criteria': self._get_seq_expr('task5')
                    }
                ],
                []
            ],
            'multigraph': True
        }

        self._assert_wf_graph(wf_name, expected_wf_graph)

        expected_wf_ex_graph = {
            'directed': True,
            'graph': {},
            'nodes': [
                {
                    'id': 'task1',
                    'name': 'task1'
                },
                {
                    'id': 'task2',
                    'name': 'task2'
                },
                {
                    'id': 'task3',
                    'name': 'task3'
                },
                {
                    'id': 'task4',
                    'name': 'task4'
                },
                {
                    'id': 'task5',
                    'name': 'task5'
                },
                {
                    'id': 'task6',
                    'name': 'task6'
                }
            ],
            'adjacency': [
                [
                    {
                        'id': 'task2',
                        'key': 0,
                        'criteria': self._get_seq_expr('task1')
                    }
                ],
                [
                    {
                        'id': 'task3',
                        'key': 0,
                        'criteria': self._get_seq_expr('task2')
                    }
                ],
                [],
                [
                    {
                        'id': 'task5',
                        'key': 0,
                        'criteria': self._get_seq_expr('task4')
                    }
                ],
                [
                    {
                        'id': 'task6',
                        'key': 0,
                        'criteria': self._get_seq_expr('task5')
                    }
                ],
                []
            ],
            'multigraph': True
        }

        self._assert_compose(wf_name, expected_wf_ex_graph)

        expected_task_seq = [
            'task1',
            'task4',
            'task2',
            'task5',
            'task3',
            'task6'
        ]

        self._assert_conduct(expected_wf_ex_graph, expected_task_seq)

    def test_branching(self):
        wf_name = 'branching'

        expected_wf_graph = {
            'directed': True,
            'graph': {},
            'nodes': [
                {
                    'id': 'task1'
                },
                {
                    'id': 'task2'
                },
                {
                    'id': 'task3'
                },
                {
                    'id': 'task4'
                },
                {
                    'id': 'task5'
                }
            ],
            'adjacency': [
                [
                    {
                        'id': 'task2',
                        'key': 0,
                        'criteria': self._get_seq_expr('task1')
                    },
                    {
                        'id': 'task4',
                        'key': 0,
                        'criteria': self._get_seq_expr('task1')
                    }
                ],
                [
                    {
                        'id': 'task3',
                        'key': 0,
                        'criteria': self._get_seq_expr('task2')
                    }
                ],
                [],
                [
                    {
                        'id': 'task5',
                        'key': 0,
                        'criteria': self._get_seq_expr('task4')
                    }
                ],
                []
            ],
            'multigraph': True
        }

        self._assert_wf_graph(wf_name, expected_wf_graph)

        expected_wf_ex_graph = {
            'directed': True,
            'graph': {},
            'nodes': [
                {
                    'id': 'task1',
                    'name': 'task1'
                },
                {
                    'id': 'task2',
                    'name': 'task2'
                },
                {
                    'id': 'task3',
                    'name': 'task3'
                },
                {
                    'id': 'task4',
                    'name': 'task4'
                },
                {
                    'id': 'task5',
                    'name': 'task5'
                }
            ],
            'adjacency': [
                [
                    {
                        'id': 'task2',
                        'key': 0,
                        'criteria': self._get_seq_expr('task1')
                    },
                    {
                        'id': 'task4',
                        'key': 0,
                        'criteria': self._get_seq_expr('task1')
                    }
                ],
                [
                    {
                        'id': 'task3',
                        'key': 0,
                        'criteria': self._get_seq_expr('task2')
                    }
                ],
                [],
                [
                    {
                        'id': 'task5',
                        'key': 0,
                        'criteria': self._get_seq_expr('task4')
                    }
                ],
                []
            ],
            'multigraph': True
        }

        self._assert_compose(wf_name, expected_wf_ex_graph)

        expected_task_seq = [
            'task1',
            'task2',
            'task4',
            'task3',
            'task5'
        ]

        self._assert_conduct(expected_wf_ex_graph, expected_task_seq)