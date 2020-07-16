# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import tokenize
from dataclasses import dataclass
from io import StringIO
from typing import Any, Dict, List, Tuple, Type, cast

from pants.base.exceptions import UnaddressableObjectError
from pants.base.parse_context import ParseContext
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.internals.target_adaptor import TargetAdaptor
from pants.util.frozendict import FrozenDict


@dataclass(frozen=True)
class SymbolTable:
    """A symbol table dict mapping symbol name to implementation class."""

    table: Dict[str, Type]


@dataclass(frozen=True)
class BuildFilePreludeSymbols:
    symbols: FrozenDict[str, Any]


class ParseError(Exception):
    """Indicates an error parsing BUILD configuration."""


class Parser:
    def __init__(self, symbol_table: SymbolTable, aliases: BuildFileAliases) -> None:
        self._symbols, self._parse_context = self._generate_symbols(symbol_table, aliases)

    @staticmethod
    def _generate_symbols(
        symbol_table: SymbolTable, aliases: BuildFileAliases,
    ) -> Tuple[Dict, ParseContext]:
        symbols: Dict = {}

        # Compute "per path" symbols.  For performance, we use the same ParseContext, which we
        # mutate to set the rel_path appropriately before it's actually used. This allows this
        # method to reuse the same symbols for all parses. Meanwhile, we set the rel_path to None,
        # so that we get a loud error if anything tries to use it before it's set.
        # TODO: See https://github.com/pantsbuild/pants/issues/3561
        parse_context = ParseContext(rel_path=None, type_aliases=symbols)

        class Registrar:
            def __init__(self, parse_context: ParseContext, type_alias: str, object_type):
                self._parse_context = parse_context
                self._type_alias = type_alias
                self._object_type = object_type

            def __call__(self, *args, **kwargs):
                if not issubclass(self._object_type, TargetAdaptor):
                    return self._object_type(*args, **kwargs)
                # Target names default to the name of the directory their BUILD file is in
                # (as long as it's not the root directory).
                if "name" not in kwargs:
                    dirname = os.path.basename(self._parse_context.rel_path)
                    if not dirname:
                        raise UnaddressableObjectError(
                            "Targets in root-level BUILD files must be named explicitly."
                        )
                    kwargs["name"] = dirname
                kwargs.setdefault("type_alias", self._type_alias)
                obj = self._object_type(**kwargs)
                self._parse_context._storage.add(obj)
                return obj

        for alias, symbol in symbol_table.table.items():
            registrar = Registrar(parse_context, alias, object_type=symbol)
            symbols[alias] = registrar
            symbols[symbol] = registrar

        if aliases.objects:
            symbols.update(aliases.objects)

        for alias, object_factory in aliases.context_aware_object_factories.items():
            symbols[alias] = object_factory(parse_context)

        return symbols, parse_context

    def parse(
        self, filepath: str, build_file_content: str, extra_symbols: BuildFilePreludeSymbols
    ) -> List[TargetAdaptor]:
        # Mutate the parse context with the new path.
        self._parse_context._storage.clear(os.path.dirname(filepath))

        # We update the known symbols with Build File Preludes. This is subtle code; functions have
        # their own globals set on __globals__ which they derive from the environment where they
        # were executed. So for each extra_symbol which comes from a separate execution
        # environment, we need to to add all of our self._symbols to those __globals__, otherwise
        # those extra symbols will not see our target aliases etc. This also means that if multiple
        # prelude files are present, they probably cannot see each others' symbols. We may choose
        # to change this at some point.
        global_symbols = dict(self._symbols)
        for k, v in extra_symbols.symbols.items():
            if hasattr(v, "__globals__"):
                v.__globals__.update(global_symbols)
            global_symbols[k] = v

        exec(build_file_content, global_symbols)
        error_on_imports(build_file_content, filepath)

        return cast(List[TargetAdaptor], list(self._parse_context._storage.objects))


def error_on_imports(build_file_content: str, filepath: str) -> None:
    # This is poor sandboxing; there are many ways to get around this. But it's sufficient to tell
    # users who aren't malicious that they're doing something wrong, and it has a low performance
    # overhead.
    if "import" not in build_file_content:
        return
    io_wrapped_python = StringIO(build_file_content)
    for token in tokenize.generate_tokens(io_wrapped_python.readline):
        token_str = token[1]
        lineno, _ = token[2]
        if token_str != "import":
            continue
        raise ParseError(
            f"Import used in {filepath} at line {lineno}. Import statements are banned in "
            "BUILD files because they can easily break Pants caching and lead to stale results. "
            "\n\nInstead, consider writing a macro (https://pants.readme.io/docs/macros) or "
            "writing a plugin (https://pants.readme.io/docs/plugins-overview)."
        )