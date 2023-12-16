#!/usr/bin/env python3


"""
Output a topological ordering of the commits in the current git repository.

The ordering goes from most recent to ancestor commits.
The choice of topological ordering is deterministic.

No `git` commands or subprocesses are called. This was verified via
`strace -f python3 topo_order_commits.py [args...] 2>&1 | grep exec`
which outputted:
```
execve(
"/w/home.04/ch/ugrad/perrott/topo-ordered-commits-test-suite/venv/bin/python3",
["python3", "topo_order_commits.py", "[args...]"],
0x7ffd21e266d8 /* 56 vars */) = 0
```
which just means the Python interpreter is running the script
and
`strace -f python3 topo_order_commits.py [args...] 2>&1 | grep environ`
`strace -f python3 topo_order_commits.py [args...] 2>&1 | grep system`
both of which outputted nothing.

Note: for pytest to pass all cases I needed to manually untar
example-repo-6.tar.gz via `tar -xzvf example-repo-6.tar.gz`

In addition to os, sys, and zlib, I used Path and re (all part of standard
library) because Path provides more readable manipulations of filepaths
and re I used for pattern matching.

Author: Samuel Perrott
Date: 11-20-2023

See https://web.cs.ucla.edu/classes/fall23/cs35L/assign/assign5.html
for in-depth explanation of output syntax.
"""


from pathlib import Path
import os
import sys
import zlib
import re


def find_git() -> Path:
    """
    Find the first (nearest) top level .git directory. If none found
    exit with status 1.

    Returns:
        Path: object containing absolute path to .git directory
    """
    abs_dir = Path.cwd()
    levels = len(abs_dir.parents)
    i = 0
    while (i < levels):  # keep going up a level until .git is found
        if (os.path.exists(abs_dir / '.git')):
            return Path(abs_dir / '.git')
        abs_dir = abs_dir.parent
        i += 1
    sys.stderr.write('Not inside a Git repository\n')
    sys.exit(1)


def get_branches(git_dir: Path) -> dict:
    """
    Find all branch names and the commit hashes they correspond to.

    Parameters:
        git_dir (Path): pathlib Path object containing path to .git directory
    Returns:
        dict: keys are branch names and values are the commit hashes
    """
    possible_paths = list(Path(git_dir / 'refs/heads').rglob('*'))
    paths = sorted([p for p in possible_paths if p.is_file()])
    return {
        p.relative_to(git_dir / 'refs/heads').as_posix(): first_line(p)
        for p in paths
    }  # alternatively: '/'.join(p.relative_to(git_dir / 'refs/heads').parts)


def first_line(file_path: Path) -> str:
    """
    Get the commit hash from the head file contents

    Parameters:
        file_path (Path): absolute path to branch name file
    Returns:
        str: commit hash
    """
    with open(file_path, 'r') as file:
        return file.readline().strip()


def get_graph(heads: dict, git_dir: Path) -> dict:
    """
    Get an unordered dictionary of all commits

    Parameters:
        heads (dict): keys are branch names and values are their commit hashes
        git_dir (Path): absolute path to .git directory
    Returns:
        dict: each key is a commit hash and value is corresponding CommitNode
    """
    graph = {}
    # as of Python 3.7, .values() and .keys() are deterministic
    to_visit = list(heads.values())
    visited = set()  # this is not used to determine topo_sorted order
    objects = Path(git_dir / 'objects')
    # DFS on each branch, collecting Nodes into a dict
    # re.I -- ignore case, re.M -- multiline: delimit lines with '\n'
    # match all 40 hex digit hashes that come after the word 'parent ' in
    # a given a line where 'parent' begins the line and the hash ends it
    parent_regex = re.compile(r'^parent\s([0-9a-f]{40})$', re.I | re.M)
    while to_visit:
        commit_hash = to_visit.pop()
        # if already visited, skip
        if (commit_hash in visited):
            continue
        # go to commit object file and extract parent hashes. 'rb' read binary
        with open(objects / commit_hash[0:2] / commit_hash[2:], 'rb') as file:
            compressed_contents = file.read()
        decompressed_contents = zlib.decompress(compressed_contents).decode(
            'utf-8', errors='ignore')
        # findall is based on parents order in commit, deterministic
        parent_hashes = parent_regex.findall(decompressed_contents)
        # add commit node to graph if needed
        if (commit_hash not in graph):
            graph[commit_hash] = CommitNode(commit_hash)
        # add parents to said node
        graph[commit_hash].set_parents(parent_hashes)
        # add each parent commit as a node
        for parent in parent_hashes:
            if (parent not in visited):
                to_visit.append(parent)
            if (parent not in graph):
                graph[parent] = CommitNode(parent)
            graph[parent].add_child(commit_hash)
        visited.add(commit_hash)
    # ensure all nodes in graph are visited
    if (len(visited) != len(graph)):
        raise Exception('Not all nodes visited') if len(visited) < len(
            graph) else Exception('Visited more nodes than in graph')
    return graph


class CommitNode:
    """
    Represents a commit in our DAG of commits.

    Attributes:
        commit_hash (str): the 40 hex digit SHA-1 hash of the commit
        parents (set): hash(es) of this commit's parent(s)
        children (set): hash(es) of the commit(s) that built off of this one
    Methods:
        rm_parent(parent_hash): removes parent_hash from parents
        add_child(child_hash): adds child_hash to children
        set_parents(parent_hashes): sets parents to parent_hashes
        get_parents(): returns parents
        get_children(): returns children
        get_hash(): returns commit_hash
    """

    def __init__(self, commit_hash: str):
        """Create a new CommitNode with commit_hash"""
        self.commit_hash = commit_hash
        self.parents = set()
        self.children = set()

    def rm_parent(self, parent_hash: str):
        """Remove parent_hash from self.parents"""
        self.parents.discard(parent_hash)

    def add_child(self, child_hash: str):
        """Add child_hash to self.children"""
        self.children.add(child_hash)

    def set_parents(self, parent_hashes: list):
        """Set self.parents to parent_hashes"""
        self.parents = set(parent_hashes)

    def get_parents(self) -> set:
        """Return self.parents"""
        return self.parents

    def get_children(self) -> set:
        """Return self.children"""
        return self.children

    def get_hash(self) -> str:
        """Return self.commit_hash"""
        return self.commit_hash


def topo_order_commits():
    """
    Main function that prints out a deterministic topological sorting of
    the commits in this git repo.
    """
    # setup
    git_dir = find_git()
    branch_heads = get_branches(git_dir)  # key: branchName, value: CommitNode
    commit_nodes = get_graph(branch_heads,
                             git_dir)  # key: hash, value: CommitNode

    # do the sorting below
    topo_sorted = []  # a list of CommitNodes

    # Note: iterating over dict is insertion order as of Python 3.7 so
    # it is deterministic

    # root_nodes contains the parent-less ancestor CommitNodes
    root_nodes = [
        node for node in commit_nodes.values() if not node.get_parents()
    ]
    while root_nodes:
        parent = root_nodes.pop()
        topo_sorted.append(parent)
        for child_hash in parent.get_children():
            child_node = commit_nodes[child_hash]
            child_node.rm_parent(parent.get_hash())
            if not child_node.get_parents():
                root_nodes.append(child_node)
    # ensure we covered all commits in our sorting
    if (len(topo_sorted) != len(commit_nodes)):
        raise Exception('Sort is not a bijection')

    # print them out
    topo_sorted.reverse()  # reverse so we start at branch heads
    # we need info about the next node for our formatting
    for node, next_node in zip(topo_sorted, topo_sorted[1:] + [None]):
        node_hash = node.get_hash()
        sys.stdout.write(node_hash)
        # add branch aliases
        if (node_hash in branch_heads.values()):
            names = [
                key for key, value in branch_heads.items()
                if value == node_hash
            ]
            for name in sorted(names):
                sys.stdout.write(' ' + name)
        # sticky ends and sticky starts if next_node is not node's parent
        if (next_node and node_hash not in next_node.get_children()):
            parent_hashes = [
                n.get_hash() for n in topo_sorted
                if node_hash in n.get_children()
            ]
            sys.stdout.write('\n' + ' '.join(parent_hashes) + '=\n')
            sys.stdout.write('\n=' + ' '.join(next_node.get_children()))
        sys.stdout.write('\n')


if __name__ == '__main__':
    topo_order_commits()
