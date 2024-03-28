#!/usr/bin/env python

import argparse

# == main compiler ==

loaded_source_files = set()
warning_is_error = False
log_source_view_size = 2

output_unit = ""

bold_escape = "\x1b[1m"
error_escape = f"{bold_escape}\x1b[31m"
warning_escape = f"{bold_escape}\x1b[33m"
reset_escape = "\x1b[0m"

# == compiler utils ==

class CompileError(Exception):
    def __init__(self, message, src_file: str, line_index: int, src: list) -> None:
        super().__init__(message)

        self.message = message
        self.src_file = src_file
        self.src = src
        self.line_index = line_index

def error_print(src_file: str, error_message: str, line_index: int, src: list):
    print(f"{error_escape}error{reset_escape}: {error_message} in source file \"{src_file}\"")
    
    for i in range((-log_source_view_size), log_source_view_size + 1):
        j = line_index + i
        
        if j < 0 or j > len(src) - 1:
            continue
        
        print(f"{bold_escape + error_escape if i == 0 else ''}  {j + 1}:  {src[j]}{reset_escape}")

    print()

def warn_print(src_file: str, warning_message: str, line_index: int, src: list):
    if warning_is_error:
        raise CompileError(warning_message, src_file, line_index, src)

    print(f"{warning_escape}warning{reset_escape}: {warning_message} in source file \"{src_file}\"")
    
    for i in range((-log_source_view_size), log_source_view_size + 1):
        j = line_index + i
        
        if j < 0 or j > len(src) - 1:
            continue
        
        print(f"{bold_escape + warning_escape if i == 0 else ''}  {j + 1}:  {src[j]}{reset_escape}")

    print()

# == compiler ==

def compile_fn(src: str, args: argparse.Namespace):
    pass

def compile_source_file(src_file: str, args: argparse.Namespace):
    loaded_source_files.add(src_file)

    # parse top-level source asts
    f = open(src_file, 'r')
    src = f.read().split('\n')

    for i, line in enumerate(src):
        l = line.strip()

        # strip comments
        l = l.split('//', 1)[0]

        if l == "":
            continue

        if l.startswith("import "):
            l = l.lstrip("import ")

            import_file = l.strip()

            # compile a new source file into output and asts
            compile_source_file(import_file, args)

        elif l.startswith("fn "):
            l = l.lstrip("fn ")

        else:
            raise CompileError("syntax error", src_file, i, src)
    
    f.close()

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