#!/usr/bin/env python

import argparse
import dataclasses
import os

# == compiler globals ==

loaded_source_files = set()

output_source = ""
defined_fn_prototypes = {}
instaciated_fns = {}

# == compiler utils ==

bold_escape = "\x1b[1m"
error_escape = f"{bold_escape}\x1b[31m"
warning_escape = f"{bold_escape}\x1b[33m"
reset_escape = "\x1b[0m"

warning_is_error = False
log_source_view_size = 2

class CompileError(Exception):
    def __init__(self, message, src_file: str, line_index: int, src: list) -> None:
        super().__init__(message)

        self.message = message
        self.src_file = src_file
        self.src = src
        self.line_index = line_index

def error_print(src_file: str, error_message: str, line_index: int, src: list):
    print(f"{error_escape}error{reset_escape}: {error_message} at \"{src_file}\":{line_index + 1}")
    
    for i in range((-log_source_view_size), log_source_view_size + 1):
        j = line_index + i
        
        if j < 0 or j > len(src) - 1:
            continue
        
        print(f"{bold_escape + error_escape if i == 0 else ''}  {j + 1}:  {src[j]}{reset_escape}")

    print()

def warn_print(src_file: str, warning_message: str, line_index: int, src: list):
    if warning_is_error:
        raise CompileError(warning_message, src_file, line_index, src)

    print(f"{warning_escape}warning{reset_escape}: {warning_message} at \"{src_file}\":{line_index + 1}")
    
    for i in range((-log_source_view_size), log_source_view_size + 1):
        j = line_index + i
        
        if j < 0 or j > len(src) - 1:
            continue
        
        print(f"{bold_escape + warning_escape if i == 0 else ''}  {j + 1}:  {src[j]}{reset_escape}")

    print()

# == source asts ==

@dataclasses.dataclass(kw_only=True)
class FnPrototypeAst:
    name: str
    line_of_definition: int
    template_args: list = dataclasses.field(default_factory=list)

    fn_src: str

    src: list
    src_file: str

@dataclasses.dataclass(kw_only=True)
class FnInstanceAst:
    name: str
    comp_name: str

    owning_lambdas: list = dataclasses.field(default_factory=list)
    tracked_stack_slices: list = dataclasses.field(default_factory=list)

    compiled_segments: list = dataclasses.field(default_factory=list)

@dataclasses.dataclass(kw_only=True)
class LambdaInstanceAst:
    owning_fn: FnPrototypeAst
    template_args: dict = dataclasses.field(default_factory=dict)

    owning_lambdas: list = dataclasses.field(default_factory=list)
    tracked_stack_slices: list = dataclasses.field(default_factory=list)

    compiled_segments: list = dataclasses.field(default_factory=list)

# == compiler ==

def compile_fn(fn_proto: FnPrototypeAst, template_args: list, args: argparse.Namespace) -> FnInstanceAst:
    i = 0
    line_index = fn_proto.line_of_definition

    # create fn instance ast

    comp_name = fn_proto.name.upper()

    if comp_name in instaciated_fns:
        return instaciated_fns[comp_name]

    fn = FnInstanceAst(name=fn_proto.name, comp_name=comp_name)
    instaciated_fns[comp_name] = fn

    # define function in output source

    current_comp_segment = ""
    current_comp_segment_depth = 1

    fn.compiled_segments.append(current_comp_segment)

    current_comp_segment = ''.join((current_comp_segment, fn.comp_name, '\n'))

    # instantiate template args

    if not len(fn_proto.template_args) == len(template_args):
        raise CompileError(f"incorrect number of template args for fn \"{fn_proto.name}\", expected {len(fn_proto.template_args)}, got {len(template_args)}", fn_proto.src_file, line_index, fn_proto.src)

    fn_src = fn_proto.fn_src
    for i, arg in enumerate(fn_proto.template_args):
        fn_src = fn_src.replace('[' + arg + ']', template_args[i])

    # compile fn bodies

    while fn_src[i] != '{':
        i += 1
    i += 1

    acc = ""

    while i < len(fn_src):
        c = fn_src[i]

        if c == '\n':
            line_index += 1
            i += 1
            continue
        elif c.split() == '':
            i += 1
            continue
        elif c == '{':
            # parse block

            if '=' in acc:
                # TODO: slice assigment
                pass
            elif acc.startswith("if"):
                pass
            elif acc.startswith("while"):
                pass
            elif acc.startswith("for"):
                pass
            else:
                # TODO: lambda parsing
                pass

            acc = ""
        
        elif c == '}':
            # end block
            acc = ""
            return fn

        elif c == ';':
            # parse expression

            if acc == "++":
                current_comp_segment = ''.join((current_comp_segment, '   ' * current_comp_segment_depth, f"PLACE\n"))
            elif acc == "--":
                current_comp_segment = ''.join((current_comp_segment, '   ' * current_comp_segment_depth, f"PICK\n"))
            elif acc.startswith("recall"):
                current_comp_segment = ''.join((current_comp_segment, '   ' * current_comp_segment_depth, fn.comp_name, '\n'))
            elif acc.startswith("commit"):
                # TODO: commit keyword
                pass
            elif '=' in acc:
                # TODO: slice assigment
                pass
            elif acc.startswith("if") or acc.startswith("while") or acc.startswith("for"):
                raise CompileError(f"syntax error - if, while, and for statements do not support bracket-less forms", src_file, line_index, fn_proto.src)
            else:
                if '(' in acc:
                    # TODO: template parsing
                    pass
                else:
                    callee_fn = defined_fn_prototypes.get(acc)

                    if callee_fn is None:
                        raise CompileError(f"call to an undefined fn \"{acc}\"", src_file, line_index, fn_proto.src)

                    current_comp_segment = ''.join((current_comp_segment, '   ' * current_comp_segment_depth, f"PLACE\n"))
            
            acc = ""
        else:
            acc += c

        i += 1
    
    raise CompileError("unexpected end of file, fn {fn_name} never closed (did you forget a \'}\'?)", src_file, i - 1, fn_proto.src)

def parse_fn(src: list, src_file: str, define_line_index: int, args: argparse.Namespace) -> FnPrototypeAst:
    fn_name = src[define_line_index].split('//', 1)[0].strip().lstrip("fn ").rstrip(" {")
    
    if ' ' in fn_name:
        raise CompileError("syntax error - fn name cannot contain spaces", src_file, define_line_index, src)

    # find end of fn
    
    end_line = -1
    clousure_depth = 0

    for i, line in enumerate(src[define_line_index:]):
        for char in line:
            if char == '{':
                clousure_depth += 1

            elif char == '}':
                clousure_depth -= 1
                
                if clousure_depth == 0:
                    end_line = i + define_line_index
                    break
                elif clousure_depth < 0:
                    raise CompileError("syntax error - unexpected '}' before any '{'", src_file, i + define_line_index, src)
    
    if end_line == -1:
        raise CompileError(f"syntax error - fn \"{fn_name}\" never closed (did you forget a \'{'}'}\'?)", src_file, len(src) - 1, src)

    # create fn ast

    if fn_name in defined_fn_prototypes:
        raise CompileError(f"redefinition of fn \"{fn_name}\" first defined at \"{defined_fn_prototypes[fn_name].src_file}\":{defined_fn_prototypes[fn_name].line_of_definition + 1}", src_file, define_line_index, src)

    # strip fn source for compile stage

    fn_src = src[define_line_index:end_line + 1]
    for i in range(len(fn_src)):
        l = fn_src[i]

        # strip comments
        l = l.split('//', 1)[0]

        l = l.strip()

        fn_src[i] = l + '\n'

    fn = FnPrototypeAst(name=fn_name, fn_src=''.join(fn_src), src=src, src_file=src_file, line_of_definition=define_line_index)
    defined_fn_prototypes[fn_name] = fn

    return fn

def compile_source_file(src_file: str, args: argparse.Namespace):
    loaded_source_files.add(os.path.realpath(src_file))

    # parse top-level source asts
    f = open(src_file, 'r')
    src = f.read().split('\n')

    i = 0
    while i < len(src):
        l = src[i].strip()

        # strip comments
        l = l.split('//', 1)[0]

        if l == "":
            i += 1
            continue

        if l.startswith("import "):
            l = l.lstrip("import ")

            import_file = l.strip()

            if os.path.realpath(import_file) in loaded_source_files:
                raise CompileError(f"cyclical import of source file \"{import_file}\"", src_file, i, src)

            # compile a new source file into output and asts
            compile_source_file(import_file, args)

        elif l.startswith("fn "):
            l = l.lstrip("fn ")

            fn = parse_fn(src, src_file, i, args)
            compile_fn(fn, [], args)
            print(defined_fn_prototypes, instaciated_fns)

            i += len(fn.src)

        else:
            raise CompileError("syntax error", src_file, i, src)

        i += 1
    
    f.close()

    # assemble output source from asts


# == argument parser ==

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='NumKa transpiler to karel-lang.', prog='numka')

    parser.add_argument('-W', choices=['none', 'all', 'err'], default='all', help='warning level')
    parser.add_argument('-o', metavar='output_file', help='output karel-lang file. all source files will be included in this karel-lang file')
    parser.add_argument('-I', metavar='import_dirs', action='append', help='add a directory to import search paths')

    parser.add_argument('source_files', nargs='*', default=[], help='source files to compile')

    args = parser.parse_args()

    if args.W == 'err':
        warning_is_error = True

    try:
        for src_file in args.source_files:
            if src_file in loaded_source_files:
                continue

            compile_source_file(src_file, args)

    except CompileError as e:
        error_print(e.src_file, e.message, e.line_index, e.src)
        exit(-1)
    except FileNotFoundError as e:
        print(f"{error_escape}error{reset_escape}: source file \"{e.filename}\" not found")
        exit(-1)