import os
from os.path import join, dirname, realpath, isfile
import argparse
import copy
import sys
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
import biotite.sequence as seq
import biotite.sequence.align as align
import biotite.sequence.io.fasta as fasta
import biotite.sequence.graphics as graphics
from .space import ColorSpace
from .optimizer import ColorOptimizer, DefaultScoreFunction
from .file import write_color_scheme


FIGURE_WIDTH = 8.0
EXAMPLE_FILE_NAME \
    = join(dirname(realpath(__file__)), "example_alignment.fasta")


def handle_error(func):
    def wrapped(*args, **kwargs):
        try:
            func(*args, **kwargs)
        except InputError as e:
            print(e, file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print("An unexpected error occured:\n", file=sys.stderr)
            raise
    return wrapped


class InputError(Exception):
    pass


@handle_error
def main(args=None, result_container=None, show_plots=True):
    parser = argparse.ArgumentParser(
        description="This program automatically generates a color scheme for "
                    "sequence alignments. "
                    "The perceptual color differences correspond to the "
                    "distances in a given substitution matrix."
                    "\n"
                    "The algorithm tries to find an optimal color scheme by "
                    "means of color differences by performing a "
                    "Metropolis-Monte-Carlo optimization in color space.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    space_group  = parser.add_argument_group(
        title="Color space",
        description=None
    )
    matrix_group = parser.add_argument_group(
        title="Substitution matrix and alphabet",
        description=None
    )
    opt_group = parser.add_argument_group(
        title="Optimization",
        description=None
    )
    output_group = parser.add_argument_group(
        title="Output files",
        description=None
    )
    vis_group    = parser.add_argument_group(
        title="Visualization",
        description=None
    )

    space_group.add_argument(
        "--dry-run", "-n", action="store_true",
        help="Show only the customized color space and terminate the program."
    )
    space_group.add_argument(
        "--smin", type=int,
        help="All colors in the space must "
            "have the specified saturation at minimum "
            "(a^2 + b^2 >= smin^2).",
        metavar="S"
    )
    space_group.add_argument(
        "--smax", type=int,
        help="All colors in the space must "
            "have the specified saturation at maximum "
            "(a^2 + b^2 <= smax^2).",
        metavar="S"
    )
    space_group.add_argument(
        "--lmin", type=int,
        help="All colors in the space must "
            "have the specified lightness at minimum.",
        metavar="L"
    )
    space_group.add_argument(
        "--lmax", type=int,
        help="All colors in the space must "
            "have the specified lightness at maximum.",
        metavar="L"
    )
    space_group.add_argument(
        "--amin", type=int,
        help="All colors in the space must "
            "have the specified 'a*' value at minimum.",
        metavar="A"
    )
    space_group.add_argument(
        "--amax", type=int,
        help="All colors in the space must "
            "have the specified 'a*' value at maximum.",
        metavar="A"
    )
    space_group.add_argument(
        "--bmin", type=int,
        help="All colors in the space must "
            "have the specified 'b*' value at minimum.",
        metavar="B"
    )
    space_group.add_argument(
        "--bmax", type=int,
        help="All colors in the space must "
            "have the specified 'b*' value at maximum.",
        metavar="B"
    )

    matrix_group.add_argument(
        "--alphabet", "-a",
        help="A custom alphabet to generate the scheme for (e.g. 'ACGT'). "
             "By default an alphabet containing the 20 amino acids is used. ",
        metavar="SYMBOLS"
    )
    matrix_group.add_argument(
        "--matrix", "-m", default="BLOSUM62",
        help="The substitution matrix to calculate the pairwise symbol "
             "distances from. "
             "Can be an NCBI substitution matrix name (e.g. 'BLOSUM62') or "
             "alternatively a substitution matrix file in NCBI format "
             "(e.g. 'blosum62.mat').",
        metavar="MATRIX"
    )

    opt_group.add_argument(
        "--contrast", default=500, type=int,
        help="The contrast factor controls how strongly the symbols are "
             "pushed to the edges of the color space. "
             "At the minimum value '0' contrast is not rewarded.",
        metavar="FACTOR"
    )
    opt_group.add_argument(
        "--constraint", "-c", nargs=4, action="append",
        help="Constrain a symbol to a fixed position in color space. "
             "This argument takes four values: a symbol, "
             "and the color channels 'l*', 'a*' and 'b*'"
             "(e.g. 'A 65 10 15')."
             "Can be repeated to add constraints for multiple symbols.",
        metavar=("SYMBOL", "L", "A", "B")
    )
    opt_group.add_argument(
        "--nsteps", default=20000, type=int,
        help="The optimization process performs simulated annealing in order "
             "to find the optimal conformation of the color scheme. "
             "This parameter sets the total amount of optimization steps. "
             "With a higher number of steps the quality of the optimization "
             "increases at the cost of a longer runtime.",
        metavar="NUMBER"
    )
    
    output_group.add_argument(
        "--scheme-file", "-f",
        type=argparse.FileType(mode="w"), default=sys.stdout,
        help="Write the generated color scheme into the specified file. "
             "The scheme is saved as Biotite-compatible JSON file. "
             "By default the scheme is output to STDOUT.",
        metavar="FILE"
    )
    output_group.add_argument(
        "--name", default="scheme",
        help="The name of the color scheme that is used in the JSON file.",
        metavar="NAME"
    )
    output_group.add_argument(
        "--score-file", type=argparse.FileType(mode="w"),
        help="Write the scores during the color scheme optimization "
             "into the specified file. "
             "Each line corresponds to one optimization step.",
        metavar="FILE"
    )

    vis_group.add_argument(
        "--lightness", type=int,
        help="Set the lightness level for color space visualization. "
             "The plots generated via the '--show-space' and the "
             "'--show-scheme' options show the color space excerpt at the "
             "given lightness level. "
             "By default the mean of the minimum and maximum lightness of the "
             "space is chosen.",
        metavar="LIGHTNESS"
    )
    vis_group.add_argument(
        "--show-space", action="store_true",
        help="Show the generated color space. "
             "The lightness of the '--lightness' option is used here. "
             "The gray area cannot be displayed in RGB space at the given "
             "lightness."
    )
    vis_group.add_argument(
        "--show-scheme", action="store_true",
        help="Show the distribution of alphabet symbols in the color space."
             "The lightness of the '--lightness' option is used here. "
             "The gray area cannot be displayed in RGB space at the given "
             "lightness."
    )
    vis_group.add_argument(
        "--show-example", action="store_true",
        help="Show an example multiple sequence alignment "
             "with newly generated color space. "
             "Cannot be used in combination with a custom '--alphabet' value."
    )
    vis_group.add_argument(
        "--show-score", action="store_true",
        help="Show a plot of the score during the optimization process."
    )

    args = parser.parse_args(args=args)


    alphabet = parse_alphabet(args.alphabet)
    matrix = parse_matrix(args.matrix, alphabet)
    
    # This lightness is only used fotr visualization purposes
    if args.lightness is not None:
        lightness = args.lightness
    elif args.lmin is not None and args.lmax is not None:
        lightness = (args.lmin + args.lmax) // 2
    else:
        lightness = 50

    space = ColorSpace()
    adjust_saturation(space, args.smin, args.smax)
    adjust_l(space, args.lmin, args.lmax)
    adjust_a(space, args.amin, args.amax)
    adjust_b(space, args.bmin, args.bmax)
    if args.dry_run:
        figure = plt.figure(figsize=(FIGURE_WIDTH, FIGURE_WIDTH))
        ax = figure.gca()
        show_space(ax, space, lightness)
        figure.tight_layout()
        if show_plots:
            plt.show()
        return

    constraints = np.full((len(alphabet), 3), np.nan)
    if args.constraint is not None:
        for symbol, l, a, b in args.constraint:
            constraints[alphabet.encode(symbol)] = (l,a,b)
    
    score_func = DefaultScoreFunction(matrix, args.contrast)
    optimizer = ColorOptimizer(
        matrix.get_alphabet1(), score_func, space, constraints
    )
    
    # Simulated annealing:
    # Temperature and step size are slowly decreased
    temps      = [100, 80, 60, 40, 20, 10, 8,   6,   4,   2,   1  ]
    temps = [t*0.02 for t in temps]
    step_sizes = [10,  8,  6,  4,  2,  1,  0.8, 0.6, 0.4, 0.2, 0.1]
    # TODO: The integer division might result in a number of actual
    # total steps, differing from the nsteps argument 
    nsteps_per_temp = args.nsteps // len(temps)

    for temp, step_size in zip(temps, step_sizes): 
        optimizer.optimize(nsteps_per_temp, temp, step_size)
    result = optimizer.get_result()

    write_scheme(args.scheme_file, result, args.name)
    if args.score_file:
        write_score(args.score_file, result)

    if args.show_space:
        figure = plt.figure(figsize=(FIGURE_WIDTH, FIGURE_WIDTH))
        ax = figure.gca()
        show_space(ax, space, lightness)
        figure.tight_layout()
    if args.show_scheme:
        figure = plt.figure(figsize=(FIGURE_WIDTH, FIGURE_WIDTH))
        ax = figure.gca()
        show_scheme(ax, space, result, lightness)
        figure.tight_layout()
    if args.show_example:
        # Check whether a custom non-amino-acid alphabet is used
        if args.alphabet is not None:
            raise InputError(
                "The example alignment can only be shown "
                "for the amino acid alphabet"
            )
        figure = plt.figure(figsize=(FIGURE_WIDTH, 2.5))
        ax = figure.gca()
        show_example(ax, result.rgb_colors)
        figure.tight_layout()
    if args.show_score:
        figure = plt.figure(figsize=(FIGURE_WIDTH, 6.0))
        ax = figure.gca()
        show_score(ax, result.scores)
        figure.tight_layout()
    if show_plots:
        plt.show()

    # In case someone wants to use the CLI results in a Python script
    if result_container is not None:
        result_container.append(result)


def parse_alphabet(alphabet_str):
    if alphabet_str is None:
        return seq.LetterAlphabet(
            seq.ProteinSequence.alphabet.get_symbols()[:20]
        )
    else:
        if " " in alphabet_str:
            raise InputError("Alphabet may not contain whitespaces")
        try:
            return seq.LetterAlphabet(alphabet_str)
        except Exception:
            raise InputError("Invalid alphabet")

def parse_matrix(matrix_str, alphabet):
    if isfile(matrix_str):
        with open(matrix_str) as f:
            matrix_dict = align.SubstitutionMatrix.dict_from_str(f.read())
            return align.SubstitutionMatrix(alphabet, alphabet, matrix_dict)
    else:
        # String is a NCBI matrix name
        upper_matrix_str = matrix_str.upper()
        if upper_matrix_str not in align.SubstitutionMatrix.list_db():
            raise InputError(
                f"'{matrix_str}' is neither a file "
                f"nor a valid NCBI substitution matrix"
            )
        return align.SubstitutionMatrix(alphabet, alphabet, upper_matrix_str)

def adjust_saturation(space, smin, smax):
    lab = space.lab
    a = lab[..., 1]
    b = lab[... ,2]
    if smin is not None:
        space.remove(a**2 + b**2 < smin**2)
    if smax is not None:
        space.remove(a**2 + b**2 > smax**2)

def adjust_l(space, lmin, lmax):
    lab = space.lab
    l = lab[..., 0]
    if lmin is not None:
        space.remove(l < lmin)
    if lmax is not None:
        space.remove(l > lmax)

def adjust_a(space, amin, amax):
    lab = space.lab
    a = lab[..., 1]
    if amin is not None:
        space.remove(a < amin)
    if amax is not None:
        space.remove(a > amax)

def adjust_b(space, bmin, bmax):
    lab = space.lab
    b = lab[..., 2]
    if bmin is not None:
        space.remove(b < bmin)
    if bmax is not None:
        space.remove(b > bmax)


def write_scheme(file, result, name):
    write_color_scheme(file, result, name)

def write_score(file, result):
    np.savetxt(file, result.scores, fmt="%.2f")


def show_space(ax, space, lightness):
    # For performance reasons, filter correct lightness
    # before converting to RGB 
    l = space.lab[..., 0]
    space = copy.deepcopy(space)
    space.remove(l != lightness)
    # Remove first dimension (length = 1)
    rgb_space = space.get_rgb_space()[lightness]
    rgb_space[np.isnan(rgb_space)] = 0.7
    ax.imshow(np.transpose(rgb_space, axes=(1,0,2)), origin="lower",
                extent=(-128, 127,-128, 127), aspect="equal")
    ax.set_xlabel("a*")
    ax.set_ylabel("b*")
    ax.set_title(f"L* = {lightness}")

def show_scheme(ax, space, result, lightness):
    s = space.space
    ax.matshow(space.space[lightness].T, extent=(-128, 127,-128, 127),
               origin="lower", cmap=ListedColormap([(0.7,0.7,0.7), (1,1,1)]))
    for symbol, pos, color in zip(
        result.alphabet, result.lab_colors, result.rgb_colors
    ):
        ax.text(pos[1], pos[2], symbol, color=color,
                ha="center", va="center", size=14, weight="heavy")
    ax.xaxis.set_ticks_position("bottom")
    ax.set_xlabel("a*")
    ax.set_ylabel("b*")
    ax.set_title(f"L* = {lightness}")

def show_example(ax, colors):
    fasta_file = fasta.FastaFile()
    fasta_file.read(EXAMPLE_FILE_NAME)
    alignment = fasta.get_alignment(fasta_file)
    alignment = alignment[:60]

    graphics.plot_alignment_type_based(
        ax, alignment, spacing=2.0, symbols_per_line=len(alignment),
        color_scheme=colors
    )

def show_score(ax, scores):
    ax.plot(scores)
    ax.set_xlabel("Step")
    ax.set_ylabel("Score")


def optimize(optimizer, n_steps, temp, step_size):
    optimizer.optimize(n_steps, temp, step_size)
    return optimizer