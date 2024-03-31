#!/usr/bin/env python

import argparse
import dataclasses
import os

# == compiler globals ==

source_file_compiled = {}

output_source = ""
defined_fn_prototypes = {}
instaciated_fns = {}

builtin_fns = {
    "step": "STEP",
    "left": "LEFT",
    "pick": "PICK",
    "place": "PLACE",
    "stop": "STOP",
}

builtit_reserved = {
    "end", "until", "repeat"
}

# == compiler utils ==

bold_escape = "\x1b[1m"
error_escape = f"{bold_escape}\x1b[31m"
warning_escape = f"{bold_escape}\x1b[33m"
reset_escape = "\x1b[0m"

warning_level = 1
log_source_view_size = 2

class CompileError(Exception):
    def __init__(self, message, src_file: str, line_index: int, src: list) -> None:
        super().__init__(message)

        self.message = message
        self.src_file = src_file
        self.src = src
        self.line_index = line_index

last_status = ""

def status_print(file: str):
    global last_status
    last_status = file

    print(f"\x1b[1K\r{bold_escape}Compiling:{reset_escape} {file}", end="")

def reset_status():
    print()
    status_print(last_status)

def error_print(src_file: str, error_message: str, line_index: int, src: list):
    print(f"\n\n{error_escape}error{reset_escape}: {error_message} at \"{src_file}\":{line_index + 1}")
    
    max_digits = len(str(line_index + log_source_view_size + 1))

    for i in range((-log_source_view_size), log_source_view_size + 1):
        j = line_index + i
        
        if j < 0 or j > len(src) - 1:
            continue
        
        print(f"{bold_escape + error_escape if i == 0 else ''}  {j + 1:0={max_digits}}:  {src[j]}{reset_escape}")

    print()

def warn_print(src_file: str, warning_message: str, line_index: int, src: list):
    if warning_level == 2:
        raise CompileError(warning_message, src_file, line_index, src)
    elif warning_level == 0:
        return

    print(f"\n\n{warning_escape}warning{reset_escape}: {warning_message} at \"{src_file}\":{line_index + 1}")
    
    max_digits = len(str(line_index + log_source_view_size))

    for i in range((-log_source_view_size), log_source_view_size + 1):
        j = line_index + i
        
        if j < 0 or j > len(src) - 1:
            continue
        
        print(f"{bold_escape + warning_escape if i == 0 else ''}  {j + 1:0={max_digits}}:  {src[j]}{reset_escape}")
    
    reset_status()

# == source asts ==

@dataclasses.dataclass(kw_only=True)
class FnPrototypeAst:
    name: str
    line_of_definition: int
    ending_line_of_definition: int

    template_args: tuple
    
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
    instance_template_args: tuple
    inherited_template_args: tuple = dataclasses.field(default_factory=tuple)

@dataclasses.dataclass(kw_only=True)
class CallLocationAst:
    caller_fn_name: str
    callee_fn_name: str

    template_args: tuple
    inherited_template_args: tuple = dataclasses.field(default_factory=tuple)
    callee_commit_dest_fn: FnPrototypeAst | None

    src: list[str]
    src_file: str
    caller_line_index: int

# == compiler ==

def parse_template_args(src: list, src_file: str, src_line: int, call_exp: str, args: argparse.Namespace) -> tuple[tuple, int]:
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
        return (tuple(), 0)
    
    # find template args clousure end
    j = i + 1

    while j < len(call_exp):
        c = call_exp[j]

        if c == '(':
            raise CompileError("syntax error - unexpected \'(\' after template expression", src_file, src_line, src)

        if c == ')':
            break

        j += 1
    
    if j == len(call_exp):
        raise CompileError("unexpected end of file - template args expression never closed", src_file, src_line, src)

    # parse template args
    template_args = call_exp[i + 1:j].split(',')

    if len(template_args) == 1 and template_args[0].strip() == '':
        # alternate syntax for no template args
        return (tuple(), j)

    for i, arg in enumerate(template_args):
        arg = arg.strip()

        if arg == '':
            raise CompileError(f"syntax error - missing template argument at position {i + 1}", src_file, src_line, src)

    return (tuple(template_args), j)

def parse_contition(src: list, src_file: str, src_line: int, cond_exp: str, args: argparse.Namespace) -> tuple[str, int]:
    size_read = 0
    orig_cond_exp = cond_exp
    
    if cond_exp.startswith("is_"):
        cond_exp = cond_exp[3:]
        size_read += 3
        invert_prefix = "IS "
    elif cond_exp.startswith("not_"):
        cond_exp = cond_exp[4:]
        size_read += 4
        invert_prefix = "ISNOT "
    else:
        raise CompileError("syntax error - condition must start with 'is_' or 'not_'", src_file, src_line, src)

    if cond_exp.startswith("wall "):
        return (invert_prefix + "WALL", 5 + size_read)
    elif cond_exp.startswith("flag "):
        return (invert_prefix + "FLAG", 5 + size_read)
    elif cond_exp.startswith("home "):
        return (invert_prefix + "HOME", 5 + size_read)
    elif cond_exp.startswith("north "):
        return (invert_prefix + "NORTH", 6 + size_read)
    elif cond_exp.startswith("south "):
        return (invert_prefix + "SOUTH", 6 + size_read)
    elif cond_exp.startswith("east "):
        return (invert_prefix + "EAST", 5 + size_read)
    elif cond_exp.startswith("west "):
        return (invert_prefix + "WEST", 5 + size_read)
    else:
        raise CompileError(f"syntax error - unknown condition \"{orig_cond_exp.strip()}\"", src_file, src_line, src)

def parse_fn(src: list, src_file: str, define_line_index: int, lambda_owner: FnInstanceAst | None, args: argparse.Namespace) -> FnPrototypeAst:
    tem_args, tem_end = parse_template_args(src, src_file, define_line_index, src[define_line_index], args)
    
    if lambda_owner == None:
        fn_name = src[define_line_index].split('//', 1)[0].strip()[3:].lstrip().split('(', 1)[0].rstrip(" {")

        if ' ' in fn_name:
            raise CompileError("syntax error - fn name cannot contain spaces", src_file, define_line_index, src)
        elif fn_name in builtit_reserved:
            raise CompileError(f"syntax error - \"{fn_name}\" is a reserved keyword by karel-lang", src_file, define_line_index, src)
    else:
        fn_name = f"{lambda_owner.name}_lambda_n{len(lambda_owner.owning_lambdas)}"

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

                    if not j + 1 == len(line.split('//', 1)[0]) and lambda_owner == None:
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

# returns a precompiled FnInstanceAst if it has already been compiled with the same template args and commit fn 
def compile_fn(fn_proto: FnPrototypeAst, call_loc: CallLocationAst, args: argparse.Namespace, inherited_template_args: tuple = tuple()) -> FnInstanceAst:
    i = 0
    line_index = fn_proto.line_of_definition

    # create fn instance ast

    if not args.g:
        comp_name = fn_proto.name + f"<cl-{call_loc.callee_commit_dest_fn.name if not call_loc.callee_commit_dest_fn is None else 'none'}-th{hash(call_loc.template_args + call_loc.inherited_template_args)}>"
    else:
        comp_name = fn_proto.name + f"<commit-loc: {call_loc.callee_commit_dest_fn.name if not call_loc.callee_commit_dest_fn is None else 'none'} | template-args: {call_loc.template_args}{f' + inherited: {call_loc.inherited_template_args}' if len(call_loc.inherited_template_args) > 0 else ''}>"

    # return FnInstanceAst if already compiled an instance with the same template set and commit fn
    if comp_name in instaciated_fns:
        return instaciated_fns[comp_name]

    fn = FnInstanceAst(name=fn_proto.name, comp_name=comp_name, commit_fn_proto=call_loc.callee_commit_dest_fn, instance_template_args=call_loc.template_args, inherited_template_args=call_loc.template_args + call_loc.inherited_template_args)
    instaciated_fns[comp_name] = fn

    # define function in output source

    current_comp_segment = ""
    current_comp_segment_depth = 1
    block_clousure_depth = 1

    # used for validating else statements
    is_last_end_if = {}

    current_comp_segment = ''.join((current_comp_segment, fn.comp_name, '\n'))

    # instantiate template args

    if not len(fn_proto.template_args) == len(call_loc.template_args):
        raise CompileError(f"incorrect number of template args for fn \"{fn_proto.name}\", expected {len(fn_proto.template_args)}, got {len(call_loc.template_args)}", call_loc.src_file, call_loc.caller_line_index, call_loc.src)

    fn_src = fn_proto.fn_src
    for i, arg in enumerate(fn_proto.template_args):
        fn_src = fn_src.replace('[' + arg + ']', call_loc.template_args[i])

    # parse and compile fn segments

    while fn_src[i] != '{':
        i += 1
    i += 1

    acc = ""

    while i < len(fn_src):
        c = fn_src[i]

        if c == '\n':
            line_index += 1

            if not len(acc) == 0 and not acc[-1] == ' ':
                acc += ' '
            
            i += 1
            continue
        elif c.strip() == '':
            if not len(acc) == 0 and not acc[-1] == ' ':
                acc += ' '
            
            i += 1
            continue
        elif c == '{':
            # parse block

            block_clousure_depth += 1

            if '=' in acc:
                # TODO: slice assigment
                pass
            elif acc.startswith("if "):
                acc = acc[3:]

                cond = parse_contition(fn_proto.src, fn_proto.src_file, line_index, acc, args)
                acc = acc[cond[1]:]

                if not acc.strip() == '':
                    raise CompileError("syntax error - expected a \'{\' after an if statement", fn_proto.src_file, line_index, fn_proto.src)

                current_comp_segment = ''.join((current_comp_segment, '   ' * current_comp_segment_depth, f"IF {cond[0]}\n"))
                is_last_end_if[current_comp_segment_depth] = True
                current_comp_segment_depth += 1

            elif acc.startswith("else"): # note: no suffixed space because else keyword doesn't have a condition
                acc = acc[4:]

                # check that the last output line is an end of an if block
                if not current_comp_segment_depth in is_last_end_if or not is_last_end_if[current_comp_segment_depth] or (not len(current_comp_segment) > 4 or not current_comp_segment[-4:] == "END\n"):
                    raise CompileError("syntax error - else statements can be only defined after an if", fn_proto.src_file, line_index, fn_proto.src)

                if not acc.strip() == '':
                    raise CompileError("syntax error - expected a \'{\' after an else statement", fn_proto.src_file, line_index, fn_proto.src)

                # remove last newline and append ', ELSE' to start the else block
                current_comp_segment = ''.join((current_comp_segment[:-1], ", ELSE\n"))
                is_last_end_if[current_comp_segment_depth] = False
                current_comp_segment_depth += 1

            elif acc.startswith("while "):
                acc = acc[6:]

                cond = parse_contition(fn_proto.src, fn_proto.src_file, line_index, acc, args)
                acc = acc[cond[1]:]

                if not acc.strip() == '':
                    raise CompileError("syntax error - expected a \'{\' after a while statement", fn_proto.src_file, line_index, fn_proto.src)

                current_comp_segment = ''.join((current_comp_segment, '   ' * current_comp_segment_depth, f"UNTIL {cond[0]}\n"))
                is_last_end_if[current_comp_segment_depth] = False
                current_comp_segment_depth += 1

            elif acc.startswith("for "):
                acc = acc[4:]

                try:
                    count = int(acc, base=0)
                    acc = acc[len(str(count)):]
                except ValueError:
                    raise CompileError("for loop count is not convertible to an integer", fn_proto.src_file, line_index, fn_proto.src)

                if not acc.strip() == '':
                    raise CompileError("syntax error - expected a \'{\' after a for statement", fn_proto.src_file, line_index, fn_proto.src)

                if count > args.max_loop_count:
                    warn_print(fn_proto.src_file, f"for loop count {count} is greater than the safe maximum of {args.max_loop_count}", line_index, fn_proto.src)

                current_comp_segment = ''.join((current_comp_segment, '   ' * current_comp_segment_depth, f"REPEAT {count}-TIMES\n"))
                is_last_end_if[current_comp_segment_depth] = False
                current_comp_segment_depth += 1

            elif acc.startswith("fn "):
                raise CompileError("syntax error - fn definitions are not allowed inside fn bodies (did you forget a \'}\'?)", fn_proto.src_file, line_index, fn_proto.src)
            else:
                # parse lambda for this fn instance

                fn_name = f"{fn.name}_lambda_n{len(fn.owning_lambdas)}"

                if fn_name in defined_fn_prototypes:
                    lambda_proto =  defined_fn_prototypes[fn_name] 
                else:
                    lambda_proto = parse_fn(fn_proto.src, fn_proto.src_file, line_index, fn, args)

                # offset to lambdas end

                clousure_depth = 0
                while i < len(fn_src):
                    char = fn_src[i]
                    
                    if char == '\n':
                        line_index += 1

                    if char == '{':
                        clousure_depth += 1

                    elif char == '}':
                        clousure_depth -= 1

                        if clousure_depth == 0:
                            break
                    
                    i += 1
                i += 1

                # parse out the template instanciation args

                l_acc = ''

                while i < len(fn_src):
                    c = fn_src[i]

                    if c == '\n':
                        line_index += 1
                        l_acc += ' '

                        if not len(l_acc) == 0 and not l_acc[-1] == ' ':
                            l_acc += ' '
                    elif c.strip() == '':
                        if not len(l_acc) == 0 and not l_acc[-1] == ' ':
                            l_acc += ' '
                    elif c == ';':
                        if '(' in l_acc and not ')' in l_acc:
                            raise CompileError("syntax error - unexpected \';\' inside a template args closure", fn_proto.src_file, line_index, fn_proto.src)

                        break
                    else:
                        if not '(' in l_acc and not c == '(':
                            raise CompileError("syntax error - expected a \';\' after a lambda definition", fn_proto.src_file, line_index, fn_proto.src)

                        l_acc += c
                    
                    i += 1

                # compile lambda fn instance
                tem_args, read_size = parse_template_args(fn_proto.src, fn_proto.src_file, line_index, l_acc, args)

                if not read_size == 0:
                    l_acc = l_acc[read_size + 1:]
                else:
                    l_acc = l_acc[1:]
                
                l_acc = l_acc.strip()

                if not l_acc == '':
                    raise CompileError("syntax error - expected a \';\' after a lambda definition", fn_proto.src_file, line_index, fn_proto.src)

                lambda_call_loc = CallLocationAst(
                    caller_fn_name=fn_proto.name,
                    callee_fn_name=lambda_proto.name,
                    template_args=tem_args,
                    inherited_template_args=fn.inherited_template_args,
                    callee_commit_dest_fn=call_loc.callee_commit_dest_fn, # lambdas can commit parents pushes
                    src=fn_proto.src,
                    src_file=fn_proto.src_file,
                    caller_line_index=line_index
                )

                # note: includes callers templates in the template hash, as parents template args can affect a child lambda
                lambda_fn_instance = compile_fn(lambda_proto, lambda_call_loc, args, fn.inherited_template_args)

                # call lambda
                current_comp_segment = ''.join((current_comp_segment, '   ' * current_comp_segment_depth, f"{lambda_fn_instance.comp_name}\n"))

                fn.owning_lambdas.append(lambda_fn_instance)
                block_clousure_depth -= 1

            acc = ""
        
        elif c == '}':
            if not acc.strip() == '':
                raise CompileError("syntax error - unexpected expression before '}' (did you forget a ';'?)", fn_proto.src_file, line_index, fn_proto.src)

            # end block
            acc = ""

            current_comp_segment_depth -= 1
            current_comp_segment = ''.join((current_comp_segment, '   ' * current_comp_segment_depth, f"END\n"))

            block_clousure_depth -= 1
            if block_clousure_depth == 0:
                fn.compiled_segments.append(current_comp_segment + '\n')

                break

        elif c == ';':
            # parse expression

            acc = acc.strip()

            if acc == "++":
                current_comp_segment = ''.join((current_comp_segment, '   ' * current_comp_segment_depth, f"PLACE\n"))
            elif acc == "--":
                current_comp_segment = ''.join((current_comp_segment, '   ' * current_comp_segment_depth, f"PICK\n"))
            elif acc in builtin_fns:
                current_comp_segment = ''.join((current_comp_segment, '   ' * current_comp_segment_depth, f"{builtin_fns[acc]}\n"))
            elif acc.startswith("recall"):
                if '(' in acc and not ')' in acc:
                    raise CompileError("syntax error - unexpected \';\' inside a template args closure", fn_proto.src_file, line_index, fn_proto.src)

                tem_args, size_read = parse_template_args(fn_proto.src, fn_proto.src_file, line_index, acc, args)
                
                if size_read == 0:
                    acc = acc[6:]
                else:
                    acc = acc[size_read + 1:]

                acc = acc.strip()

                if not acc == '':
                        raise CompileError(f"syntax error - expected a ';' after a recall keyword", fn_proto.src_file, line_index, fn_proto.src)

                # recompile fn with possibly new template args
                recall_loc = CallLocationAst(
                    caller_fn_name=fn_proto.name, 
                    callee_fn_name=fn_proto.name,
                    template_args=tem_args,
                    callee_commit_dest_fn=None,
                    src=fn_proto.src,
                    src_file=fn_proto.src_file,
                    caller_line_index=line_index
                )

                recall_fn_instance = compile_fn(fn_proto, recall_loc, args)

                current_comp_segment = ''.join((current_comp_segment, '   ' * current_comp_segment_depth, recall_fn_instance.comp_name, '\n'))
            elif acc.startswith("commit"):
                if call_loc.callee_commit_dest_fn is not None:
                    if '(' in acc and not ')' in acc:
                        raise CompileError("syntax error - unexpected \';\' inside a template args closure", fn_proto.src_file, line_index, fn_proto.src)

                    tem_args, size_read = parse_template_args(fn_proto.src, fn_proto.src_file, line_index, acc, args)
                    
                    if size_read == 0:
                        acc = acc[6:]
                    else:
                        acc = acc[size_read + 1:]

                    acc = acc.strip()

                    if not acc == '':
                        raise CompileError(f"syntax error - expected a ';' after a commit keyword", fn_proto.src_file, line_index, fn_proto.src)

                    # compile target commit location
                    commit_loc = CallLocationAst(
                        caller_fn_name=fn_proto.name, 
                        callee_fn_name=call_loc.callee_commit_dest_fn.name,
                        template_args=tem_args,
                        callee_commit_dest_fn=None, # commit already done
                        src=fn_proto.src,
                        src_file=fn_proto.src_file,
                        caller_line_index=line_index
                    )

                    commit_dest_fn = compile_fn(call_loc.callee_commit_dest_fn, commit_loc, args)

                    current_comp_segment = ''.join((current_comp_segment, '   ' * current_comp_segment_depth, commit_dest_fn.comp_name, '\n'))
                else:
                    warn_print(fn_proto.src_file, f"commit keyword used while not pushing to stack, called from fn \"{call_loc.caller_fn_name}\"", line_index, fn_proto.src)

            elif '=' in acc:
                # TODO: slice assigment
                pass
            elif acc.startswith("if") or acc.startswith("while") or acc.startswith("for"):
                raise CompileError(f"syntax error - if, while, and for statements do not support bracket-less forms", fn_proto.src_file, line_index, fn_proto.src)
            else:
                if '(' in acc and not ')' in acc:
                    raise CompileError("syntax error - unexpected \';\' inside a template args closure", fn_proto.src_file, line_index, fn_proto.src)

                tem_args, size_read = parse_template_args(fn_proto.src, fn_proto.src_file, line_index, acc, args)

                if size_read == 0:
                    if len(acc.split(' ', 1)) == 2:
                        raise CompileError(f"syntax error - expected a \';\' after a fn call", fn_proto.src_file, line_index, fn_proto.src)
                    
                    acc = acc.split(' ', 1)[0]
                else:
                    if not acc[size_read + 1:].strip() == '':
                        raise CompileError(f"syntax error - expected a \';\' after a fn call", fn_proto.src_file, line_index, fn_proto.src)

                    acc = acc.split('(', 1)[0].strip()

                # fn call
                callee_fn = defined_fn_prototypes.get(acc)

                if callee_fn is None:
                    raise CompileError(f"call to an undefined fn \"{acc}\"", fn_proto.src_file, line_index, fn_proto.src)

                fn_call_loc = CallLocationAst(
                    caller_fn_name=fn_proto.name,
                    callee_fn_name=acc,
                    template_args=tem_args,
                    callee_commit_dest_fn=None,
                    src=fn_proto.src,
                    src_file=fn_proto.src_file,
                    caller_line_index=line_index
                )

                callee_fn_instance = compile_fn(callee_fn, fn_call_loc, args)

                current_comp_segment = ''.join((current_comp_segment, '   ' * current_comp_segment_depth, f"{callee_fn_instance.comp_name}\n"))
            
            acc = ""
        else:
            acc += c

        i += 1
    
    if i == len(fn_src):
        raise CompileError(f"unexpected end of file, fn \"{fn.name}\" never closed (did you forget a \'{'}'}\'?)", fn_proto.src_file, i - 1, fn_proto.src)

    # assemble owned compiled segments in output

    global output_source

    for seg in fn.compiled_segments:
        output_source = ''.join((output_source, seg.upper()))

    return fn

def compile_source_file(src_file: str, args: argparse.Namespace) -> None:
    source_file_compiled[os.path.realpath(src_file)] = False

    status_print(src_file)

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

            if not os.path.realpath(import_file) in source_file_compiled:
                # compile a new source file into output and asts
                compile_source_file(import_file, args)

            elif not source_file_compiled[os.path.realpath(import_file)]:
                raise CompileError(f"cyclical import of source file \"{import_file}\"", src_file, i, src)

        elif l.startswith("fn "):
            l = l[3:].lstrip()

            fn = parse_fn(src, src_file, i, None, args)

            if fn.top_level_implicit_usage:
                call_loc = CallLocationAst(
                    caller_fn_name="(top-level)",
                    callee_fn_name=fn.name,
                    template_args=tuple(),
                    callee_commit_dest_fn=None,
                    src=src,
                    src_file=src_file,
                    caller_line_index=fn.line_of_definition
                )

                compile_fn(fn, call_loc, args)

            i += fn.ending_line_of_definition - fn.line_of_definition

        else:
            raise CompileError("syntax error - expression outside of a fn", src_file, i, src)

        i += 1
    
    f.close()
    source_file_compiled[os.path.realpath(src_file)] = True


# == argument parser ==

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='NumKa language transpiler to karel-lang.', prog='numka')

    parser.add_argument('-W', choices=['none', 'all', 'err'], default='all', help='warning level')
    parser.add_argument('-o', default='out.kl', metavar='output_file', help='output karel-lang file. all source files will be compiled into this file')
    parser.add_argument('-I', metavar='import_dirs', action='append', help='add a directory to import search paths')
    parser.add_argument('-v', default=False, action='store_true', help='enable verbose mode, will print internal asts')
    parser.add_argument('-g', default=False, action='store_true', help='enable debug mode, generate human-readable fn names for debugging')

    parser.add_argument('-lmax-for-loop-count', dest='max_loop_count', default=65535, type=int, help='max safe amount of iterations for a single for loop')

    parser.add_argument('source_files', nargs='*', default=[], help='source files to compile')

    args = parser.parse_args()

    if args.W == 'err':
        warning_level = 2
    elif args.W == 'none':
        warning_level = 0

    try:
        for src_file in args.source_files:
            if src_file in source_file_compiled:
                continue

            compile_source_file(src_file, args)
        
        if args.v:
            print(defined_fn_prototypes, '\n')
            print(instaciated_fns, '\n')

        o = open(args.o, 'w')
        o.write(output_source)
        o.close()

        print(f"\x1b[1K\rCompiled {bold_escape}{len(source_file_compiled)}{reset_escape} source files into {bold_escape}{args.o}{reset_escape} successfully!")

    except CompileError as e:
        if args.v:
            print(defined_fn_prototypes, '\n')
            print(instaciated_fns, '\n')

        error_print(e.src_file, e.message, e.line_index, e.src)
        print(f"Compilation {error_escape}failed{reset_escape} in source file {bold_escape}{e.src_file}{reset_escape}!")
        exit(-1)
    except FileNotFoundError as e:
        print(f"\n\n{error_escape}error{reset_escape}: source file \"{e.filename}\" not found")
        exit(-1)