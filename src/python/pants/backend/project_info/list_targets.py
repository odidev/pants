# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Dict, cast

from pants.engine.addresses import Address, Addresses
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.rules import goal_rule
from pants.engine.selectors import Get
from pants.engine.target import DescriptionField, ProvidesField, Targets


class ListOptions(LineOriented, GoalSubsystem):
    """Lists all targets matching the file or target arguments."""

    name = "list"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--provides",
            type=bool,
            help=(
                "List only targets that provide an artifact, displaying the columns specified by "
                "--provides-columns."
            ),
        )
        register(
            "--provides-columns",
            default="address,artifact_id",
            help=(
                "Display these columns when --provides is specified. Available columns are: "
                "address, artifact_id, repo_name, repo_url, push_db_basedir"
            ),
            removal_version="2.0.1.dev0",
            removal_hint=(
                "The option `--provides-columns` no longer does anything. It was specific to the "
                "JVM backend, so no longer makes sense with Pants 2.0 initially only supporting "
                "Python."
            ),
        )
        register(
            "--documented",
            type=bool,
            help="Print only targets that are documented with a description.",
        )


class List(Goal):
    subsystem_cls = ListOptions


@goal_rule
async def list_targets(addresses: Addresses, options: ListOptions, console: Console) -> List:
    if not addresses:
        console.print_stderr(f"WARNING: No targets were matched in goal `{options.name}`.")
        return List(exit_code=0)

    provides_enabled = options.values.provides
    documented_enabled = options.values.documented
    if provides_enabled and documented_enabled:
        raise ValueError(
            "Cannot specify both `--list-documented` and `--list-provides` at the same time. "
            "Please choose one."
        )

    if provides_enabled:
        targets = await Get(Targets, Addresses, addresses)
        addresses_with_provide_artifacts = {
            tgt.address: tgt[ProvidesField].value
            for tgt in targets
            if tgt.get(ProvidesField).value is not None
        }
        with options.line_oriented(console) as print_stdout:
            for address, artifact in addresses_with_provide_artifacts.items():
                print_stdout(f"{address.spec} {artifact}")
        return List(exit_code=0)

    if documented_enabled:
        targets = await Get(Targets, Addresses, addresses)
        addresses_with_descriptions = cast(
            Dict[Address, str],
            {
                tgt.address: tgt[DescriptionField].value
                for tgt in targets
                if tgt.get(DescriptionField).value is not None
            },
        )
        with options.line_oriented(console) as print_stdout:
            for address, description in addresses_with_descriptions.items():
                formatted_description = "\n  ".join(description.strip().split("\n"))
                print_stdout(f"{address.spec}\n  {formatted_description}")
        return List(exit_code=0)

    with options.line_oriented(console) as print_stdout:
        for address in sorted(addresses):
            print_stdout(address)
    return List(exit_code=0)


def rules():
    return [list_targets]