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
verbose_mode = False
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
    
    max_digits = len(str(line_index + log_source_view_size + 1))

    for i in range((-log_source_view_size), log_source_view_size + 1):
        j = line_index + i
        
        if j < 0 or j > len(src) - 1:
            continue
        
        print(f"{bold_escape + error_escape if i == 0 else ''}  {j + 1:0={max_digits}}:  {src[j]}{reset_escape}")

    print()

def warn_print(src_file: str, warning_message: str, line_index: int, src: list):
    if warning_is_error:
        raise CompileError(warning_message, src_file, line_index, src)

    print(f"{warning_escape}warning{reset_escape}: {warning_message} at \"{src_file}\":{line_index + 1}")
    
    max_digits = len(str(line_index + log_source_view_size))

    for i in range((-log_source_view_size), log_source_view_size + 1):
        j = line_index + i
        
        if j < 0 or j > len(src) - 1:
            continue
        
        print(f"{bold_escape + warning_escape if i == 0 else ''}  {j + 1:0={max_digits}}:  {src[j]}{reset_escape}")

    print()

# == source asts ==

@dataclasses.dataclass(kw_only=True)
class FnPrototypeAst:
    name: str
    line_of_definition: int
    ending_line_of_definition: int
    template_args: list
    
    # if matches top-level requrements (no templates, no commit) it will get compiled into output even when never used
    top_level_implicit_usage: bool

    fn_src: str

    src: list
    src_file: str

@dataclasses.dataclass(kw_only=True)
class FnInstanceAst:
    name: str
    comp_name: str

    owning_lambdas: list = dataclasses.field(default_factory=list)
    tracked_stack_slices: list = dataclasses.field(default_factory=list)

    compiled_segments: list[str] = dataclasses.field(default_factory=list[str])

    commit_fn_proto: FnPrototypeAst | None = None
    instance_template_args: list

@dataclasses.dataclass(kw_only=True)
class CallLocationAst:
    caller_fn_name: str
    callee_fn_name: str

    template_args: list[str]
    callee_commit_dest_fn: FnPrototypeAst | None

    src: list[str]
    src_file: str
    caller_line_index: int

@dataclasses.dataclass(kw_only=True)
class LambdaInstanceAst:
    owning_fn: FnPrototypeAst
    template_args: dict = dataclasses.field(default_factory=dict)

    owning_lambdas: list = dataclasses.field(default_factory=list)
    tracked_stack_slices: list = dataclasses.field(default_factory=list)

    compiled_segments: list = dataclasses.field(default_factory=list)

# == compiler ==

def parse_template_args(src: list, src_file: str, src_line: int, call_exp: str, args: argparse.Namespace) -> tuple[list, int]:
    # find template args clousure begining
    i = 0

    while i < len(call_exp):
        c = call_exp[i]

        if c == ')':
            raise CompileError("syntax error - unexpected \')\' before \'(\' in a call expression", src_file, src_line, src)

        if c == '(':
            break

        i += 1

    if i == len(call_exp):
        # no templates args used
        return ([], 0)
    
    # find template args clousure end
    j = i + 1

    while j < len(call_exp):
        c = call_exp[j]

        if c == '(':
            raise CompileError("syntax error - unexpected \'(\' after expression", src_file, src_line, src)

        if c == ')':
            break

        j += 1
    
    # parse template args
    template_args = call_exp[i + 1:j].split(',')

    if len(template_args) == 1 and template_args[0] == '':
        # alternate syntax for no template args
        return ([], j)

    for i, arg in enumerate(template_args):
        arg = arg.strip()

        if arg == '':
            raise CompileError(f"syntax error - missing template argument at position {i + 1}", src_file, src_line, src)

    return (template_args, j)

def parse_contition(src: list, src_file: str, src_line: int, cond_exp: str, args: argparse.Namespace) -> str:
    pass

# returns a precompiled FnInstanceAst if it has already been compiled with the same template args and commit fn 
def compile_fn(fn_proto: FnPrototypeAst, call_loc: CallLocationAst, args: argparse.Namespace) -> FnInstanceAst:
    i = 0
    line_index = fn_proto.line_of_definition

    # create fn instance ast

    comp_name = fn_proto.name.upper()

    # return FnInstanceAst if already compiled an instance with the same template set and commit fn
    if comp_name in instaciated_fns and instaciated_fns[comp_name].instance_template_args == call_loc.template_args and instaciated_fns[comp_name].commit_fn_proto == call_loc.callee_commit_dest_fn:
        return instaciated_fns[comp_name]

    fn = FnInstanceAst(name=fn_proto.name, comp_name=comp_name, commit_fn_proto=call_loc.callee_commit_dest_fn, instance_template_args=call_loc.template_args)
    instaciated_fns[comp_name] = fn

    # define function in output source

    current_comp_segment = ""
    current_comp_segment_depth = 1
    block_clousure_depth = 1

    fn.compiled_segments.append(current_comp_segment)

    current_comp_segment = ''.join((current_comp_segment, fn.comp_name, '\n'))

    # instantiate template args

    if not len(fn_proto.template_args) == len(call_loc.template_args):
        raise CompileError(f"incorrect number of template args for fn \"{fn_proto.name}\", expected {len(fn_proto.template_args)}, got {len(call_loc.template_args)}", call_loc.src_file, call_loc.caller_line_index, call_loc.src)

    fn_src = fn_proto.fn_src
    for i, arg in enumerate(fn_proto.template_args):
        fn_src = fn_src.replace('[' + arg + ']', call_loc.template_args[i])

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

            if not len(acc) == 0 and not acc[-1] == ' ':
                acc += ' '
            
            continue
        elif c.split() == '' and not len(acc) == 0 and not acc[-1] == ' ':
            acc += ' '
            i += 1
            continue
        elif c == '{':
            # parse block

            block_clousure_depth += 1

            if '=' in acc:
                # TODO: slice assigment
                pass
            elif acc.startswith("if"):
                pass
            elif acc.startswith("while"):
                pass
            elif acc.startswith("for"):
                pass
            elif acc.startswith("fn"):
                raise CompileError(f"syntax error - fn definitions are not allowed inside fn bodies (did you forget a \'{'}'}\'?)", src_file, line_index, fn_proto.src)
            else:
                # TODO: lambda parsing
                pass

            acc = ""
        
        elif c == '}':
            # end block
            acc = ""

            block_clousure_depth -= 1
            if block_clousure_depth == 0:
                return fn

        elif c == ';':
            # parse expression

            acc = acc.strip()

            if acc == "++":
                current_comp_segment = ''.join((current_comp_segment, '   ' * current_comp_segment_depth, f"PLACE\n"))
            elif acc == "--":
                current_comp_segment = ''.join((current_comp_segment, '   ' * current_comp_segment_depth, f"PICK\n"))
            elif acc.startswith("recall"):
                tem_args, size_read = parse_template_args(fn_proto.src, fn_proto.src_file, line_index, acc, args)
                
                if size_read == 0:
                    acc = acc[6:]
                else:
                    acc = acc[size_read + 1:]

                acc = acc.strip()

                if not acc == '':
                        raise CompileError(f"syntax error - expected a ';' after a recall keyword", src_file, line_index, fn_proto.src)

                # recompile fn with possibly new template args
                call_loc = CallLocationAst(
                    caller_fn_name=fn_proto.name, 
                    callee_fn_name=fn_proto.name,
                    template_args=tem_args,
                    callee_commit_dest_fn=None,
                    src=fn_proto.src,
                    src_file=src_file,
                    caller_line_index=line_index
                )

                recall_fn_instance = compile_fn(fn_proto, call_loc, args)

                current_comp_segment = ''.join((current_comp_segment, '   ' * current_comp_segment_depth, recall_fn_instance.comp_name, '\n'))
            elif acc.startswith("commit"):
                if call_loc.callee_commit_dest_fn is not None:
                    tem_args, size_read = parse_template_args(fn_proto.src, fn_proto.src_file, line_index, acc, args)
                    
                    if size_read == 0:
                        acc = acc[6:]
                    else:
                        acc = acc[size_read + 1:]

                    acc = acc.strip()

                    if not acc == '':
                        raise CompileError(f"syntax error - expected a ';' after a commit keyword", src_file, line_index, fn_proto.src)

                    # compile target commit location
                    call_loc = CallLocationAst(
                        caller_fn_name=fn_proto.name, 
                        callee_fn_name=call_loc.callee_commit_dest_fn.name,
                        template_args=tem_args,
                        callee_commit_dest_fn=None, # commit already done
                        src=fn_proto.src,
                        src_file=src_file,
                        caller_line_index=line_index
                    )

                    commit_dest_fn = compile_fn(call_loc.callee_commit_dest_fn, call_loc, args)

                    current_comp_segment = ''.join((current_comp_segment, '   ' * current_comp_segment_depth, commit_dest_fn.comp_name, '\n'))
                else:
                    warn_print(src_file, f"commit keyword used while not pushing to stack, called from fn \"{call_loc.caller_fn_name}\"", line_index, fn_proto.src)

            elif '=' in acc:
                # TODO: slice assigment
                pass
            elif acc.startswith("if") or acc.startswith("while") or acc.startswith("for"):
                raise CompileError(f"syntax error - if, while, and for statements do not support bracket-less forms", src_file, line_index, fn_proto.src)
            else:
                tem_args, size_read = parse_template_args(fn_proto.src, fn_proto.src_file, line_index, acc, args)

                if size_read == 0:
                    if len(acc.split(' ', 1)) == 2:
                        raise CompileError(f"syntax error - expected a \';\' after a fn call", src_file, line_index, fn_proto.src)
                    
                    acc = acc.split(' ', 1)[0]
                else:
                    if not acc[size_read + 1:].strip() == '':
                        raise CompileError(f"syntax error - expected a \';\' after a fn call", src_file, line_index, fn_proto.src)

                    acc = acc.split('(', 1)[0].strip()

                # fn call
                callee_fn = defined_fn_prototypes.get(acc)

                if callee_fn is None:
                    raise CompileError(f"call to an undefined fn \"{acc}\"", src_file, line_index, fn_proto.src)

                call_loc = CallLocationAst(
                    caller_fn_name=fn_proto.name,
                    callee_fn_name=acc,
                    template_args=tem_args,
                    callee_commit_dest_fn=None,
                    src=fn_proto.src,
                    src_file=src_file,
                    caller_line_index=line_index
                )

                callee_fn_instance = compile_fn(callee_fn, call_loc, args)

                current_comp_segment = ''.join((current_comp_segment, '   ' * current_comp_segment_depth, f"{callee_fn_instance.comp_name}\n"))
            
            acc = ""
        else:
            acc += c

        i += 1
    
    raise CompileError("unexpected end of file, fn {fn_name} never closed (did you forget a \'}\'?)", src_file, i - 1, fn_proto.src)

def parse_fn(src: list, src_file: str, define_line_index: int, args: argparse.Namespace) -> FnPrototypeAst:
    tem_args, tem_end = parse_template_args(src, src_file, define_line_index, src[define_line_index], args)
    
    fn_name = src[define_line_index].split('//', 1)[0].strip()[3:].lstrip().split('(', 1)[0].rstrip(" {")
    
    if ' ' in fn_name:
        raise CompileError("syntax error - fn name cannot contain spaces", src_file, define_line_index, src)
    
    # find end of fn
    
    end_line = -1
    clousure_depth = 0

    for i, line in enumerate(src[define_line_index:]):
        for j, char in enumerate(line):
            if char == '{':
                clousure_depth += 1

            elif char == '}':
                clousure_depth -= 1
                
                if clousure_depth == 0:
                    end_line = i + define_line_index

                    if not j + 1 == len(line.split('//', 1)[0].strip()):
                        raise CompileError("syntax error - expected a new line after fn final \'}\'", src_file, i + define_line_index, src) 

                    break
                elif clousure_depth < 0:
                    raise CompileError("syntax error - unexpected '}' before any '{'", src_file, i + define_line_index, src)
        
        if not end_line == -1:
            break
    
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

    # test for top-level implicit usage

    inline_fn_src = ''.join(fn_src)
    implicit_usage = True

    # must not use templates to be implicitly used
    if not len(tem_args) == 0:
        implicit_usage = False

    # must not use the commit keyword to be implicitly used
    # FIXME: might give false positive with a fn name that ends with 'commit'
    elif "commit(" in inline_fn_src or "commit " in inline_fn_src or "commit;" in inline_fn_src:
        implicit_usage = False

    fn = FnPrototypeAst(name=fn_name, fn_src=inline_fn_src, src=src, src_file=src_file, ending_line_of_definition=end_line, line_of_definition=define_line_index, template_args=tem_args, top_level_implicit_usage=implicit_usage)
    defined_fn_prototypes[fn_name] = fn

    return fn

def compile_source_file(src_file: str, args: argparse.Namespace) -> None:
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
            l = l[7:]

            import_file = l.strip()

            if os.path.realpath(import_file) in loaded_source_files:
                raise CompileError(f"cyclical import of source file \"{import_file}\"", src_file, i, src)

            # compile a new source file into output and asts
            compile_source_file(import_file, args)

        elif l.startswith("fn "):
            l = l[3:].lstrip()

            fn = parse_fn(src, src_file, i, args)

            if fn.top_level_implicit_usage:
                call_loc = CallLocationAst(
                    caller_fn_name="(top-level)",
                    callee_fn_name=fn.name,
                    template_args=[],
                    callee_commit_dest_fn=None,
                    src=src,
                    src_file=src_file,
                    caller_line_index=fn.line_of_definition
                )

                compile_fn(fn, call_loc, args)

            i += fn.ending_line_of_definition - fn.line_of_definition

        else:
            raise CompileError("syntax error", src_file, i, src)

        i += 1
    
    f.close()

    # assemble output source from asts


# == argument parser ==

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='NumKa language transpiler to karel-lang.', prog='numka')

    parser.add_argument('-W', choices=['none', 'all', 'err'], default='all', help='warning level')
    parser.add_argument('-o', metavar='output_file', help='output karel-lang file. all source files will be compiled into this file')
    parser.add_argument('-I', metavar='import_dirs', action='append', help='add a directory to import search paths')
    parser.add_argument('-v', default=False, action='store_true', help='enable verbose mode, will print internal asts')

    parser.add_argument('source_files', nargs='*', default=[], help='source files to compile')

    args = parser.parse_args()

    if args.W == 'err':
        warning_is_error = True
    
    verbose_mode = args.v

    try:
        for src_file in args.source_files:
            if src_file in loaded_source_files:
                continue

            compile_source_file(src_file, args)
        
        if verbose_mode:
            print(defined_fn_prototypes, '\n')
            print(instaciated_fns, '\n')

    except CompileError as e:
        if verbose_mode:
            print(defined_fn_prototypes, '\n')
            print(instaciated_fns, '\n')

        error_print(e.src_file, e.message, e.line_index, e.src)
        exit(-1)
    except FileNotFoundError as e:
        print(f"{error_escape}error{reset_escape}: source file \"{e.filename}\" not found")
        exit(-1)