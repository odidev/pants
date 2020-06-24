# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.base.workunit import WorkUnit
from pants.goal.task_registrar import TaskRegistrar as task
from pants.task.task import Task


def register_goals():
    task(name="run-dummy-workunit", action=TestWorkUnitTask).install()


class TestWorkUnitTask(Task):
    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register("--success", default=False, type=bool)

    def execute(self):
        result = WorkUnit.SUCCESS if self.get_options().success else WorkUnit.FAILURE

        # This creates workunit and marks it as failure.
        with self.context.new_workunit("dummy") as workunit:
            workunit.set_outcome(result)
