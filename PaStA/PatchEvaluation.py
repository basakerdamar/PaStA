from enum import Enum
import functools
from fuzzywuzzy import fuzz
from multiprocessing import Pool, cpu_count
import pickle
from statistics import mean
from subprocess import call
import sys
import termios
import tty

from PaStA.PatchStack import get_commit
from PaStA import config


class EvaluationType(Enum):
    PatchStack = 1
    Upstream = 2


class SimRating:
    def __init__(self, msg, diff, diff_lines_ratio):
        """
        :param msg: Message rating
        :param diff: Diff rating
        :param diff_lines_ration: Ratio of number of lines shorter diff to longer diff
        """
        self._msg = msg
        self._diff = diff
        self._diff_lines_ratio = diff_lines_ratio

    @property
    def msg(self):
        return self._msg

    @property
    def diff(self):
        return self._diff

    @property
    def diff_lines_ratio(self):
        return self._diff_lines_ratio

    def __lt__(self, other):
        return self.msg + self.diff < other.msg + other.diff


class EvaluationResult(dict):
    """
    An evaluation is a dictionary with a commit hash as key,
    and a list of tuples (hash, SimRating) as value.
    """

    def __init__(self, eval_type, *args, **kwargs):
        dict.__init__(self, *args, **kwargs)
        self.universe = set()
        self._eval_type = eval_type

    @property
    def eval_type(self):
        return self._eval_type

    def merge(self, other):
        if self.eval_type != other.eval_type:
            raise ValueError('Unable to merge results of different types')

        # Check if this key already exists in the check_list
        # if yes, then append to the list
        for key, value in other.items():
            if key in self:
                self[key] += value
            else:
                self[key] = value

    def to_file(self, filename):
        # Sort by SimRating
        for i in self.keys():
            self[i].sort(key=lambda x: x[1], reverse=True)

        with open(filename, 'wb') as f:
            pickle.dump(self, f, pickle.HIGHEST_PROTOCOL)

    def set_universe(self, universe):
        self.universe = set(universe)

    @staticmethod
    def from_file(filename):
        with open(filename, 'rb') as f:
            return pickle.load(f)

    def interactive_rating(self, equivalence_class, false_positive_list,
                           thresholds, respect_commitdate=False, upstream_rating=True):

        already_false_positive = 0
        already_detected = 0
        auto_accepted = 0
        auto_declined = 0
        accepted = 0
        declined = 0
        skipped = 0
        skipped_by_dlr = 0
        skipped_by_commit_date = 0

        halt_save = False

        for i in self.universe:
            equivalence_class.insert_single(i)

        # Convert the dictionary of evaluation results to a sorted list,
        # sorted by its SimRating
        sorted_er = list(self.items())
        sorted_er.sort(key=lambda x: x[1][0][1])

        for orig_commit_hash, candidates in sorted_er:

            if halt_save:
                break

            for cand_commit_hash, sim_rating in candidates:
                # Check if both commit hashes are the same
                if cand_commit_hash == orig_commit_hash:
                    continue

                # Check if patch is already known as false positive
                if orig_commit_hash in false_positive_list and \
                   cand_commit_hash in false_positive_list[orig_commit_hash]:
                    already_false_positive += 1
                    continue

                # Check if those two patches are already related
                if equivalence_class.is_related(orig_commit_hash, cand_commit_hash):
                    already_detected += 1
                    continue

                if sim_rating.diff_lines_ratio < thresholds.diff_lines_ratio:
                    skipped_by_dlr += 1
                    continue

                if respect_commitdate:
                    l = get_commit(orig_commit_hash)
                    r = get_commit(cand_commit_hash)
                    if l.commit_date > r.commit_date:
                        skipped_by_commit_date += 1
                        continue


                # Weight by message_diff_weight
                rating = thresholds.message_diff_weight * sim_rating.msg +\
                         (1-thresholds.message_diff_weight) * sim_rating.diff

                # Maybe we can autoaccept the patch?
                if rating >= thresholds.autoaccept:
                    auto_accepted += 1
                    yns = 'y'
                # or even automatically drop it away?
                elif rating < thresholds.interactive:
                    auto_declined += 1
                    continue
                # Nope? Then let's do an interactive rating by a human
                else:
                    yns = ''
                    compare_hashes(orig_commit_hash, cand_commit_hash)
                    print('Length of list of candidates: %d' % len(candidates))
                    print('Rating: %3.2f (%3.2f message and %3.2f diff, diff length ratio: %3.2f)' %
                          (rating, sim_rating.msg, sim_rating.diff, sim_rating.diff_lines_ratio))
                    print('(y)ay or (n)ay or (s)kip?  To abort: halt and (d)iscard, (h)alt and save')

                if yns not in {'y', 'n', 's', 'd', 'h'}:
                    while yns not in {'y', 'n', 's', 'd', 'h'}:
                        yns = getch()
                        if yns == 'y':
                            accepted += 1
                        elif yns == 'n':
                            declined += 1
                        elif yns == 's':
                            skipped += 1
                        elif yns == 'd':
                            quit()
                        elif yns == 'h':
                            halt_save = True
                            break

                if yns == 'y':
                    if upstream_rating:
                        equivalence_class.set_property(orig_commit_hash, cand_commit_hash)
                        # Upstream rating can not have multiple candidates. So break after the first match
                        break
                    else:
                        equivalence_class.insert(orig_commit_hash, cand_commit_hash)
                elif yns == 'n':
                    if orig_commit_hash in false_positive_list:
                        false_positive_list[orig_commit_hash].append(cand_commit_hash)
                    else:
                        false_positive_list[orig_commit_hash] = [cand_commit_hash]

        equivalence_class.optimize()

        print('\n\nSome statistics:')
        print(' Interactive Accepted: ' + str(accepted))
        print(' Automatically accepted: ' + str(auto_accepted))
        print(' Interactive declined: ' + str(declined))
        print(' Automatically declined: ' + str(auto_declined))
        print(' Skipped: ' + str(skipped))
        print(' Skipped due to previous detection: ' + str(already_detected))
        print(' Skipped due to false positive mark: ' + str(already_false_positive))
        print(' Skipped by diff length ratio mismatch: ' + str(skipped_by_dlr))
        if respect_commitdate:
            print(' Skipped by commit date mismatch: ' + str(skipped_by_commit_date))


class DictList(dict):
    def __init__(self, *args, **kwargs):
        dict.__init__(self, *args, **kwargs)

    def to_file(self, filename):
        if len(self) == 0:
            return

        with open(filename, 'w') as f:
            f.write('\n'.join(map(lambda x: str(x[0]) + ' ' + ' '.join(sorted(x[1])), sorted(self.items()))) + '\n')
            f.close()

        with open(filename + '.pkl', 'wb') as f:
            pickle.dump(self, f, pickle.HIGHEST_PROTOCOL)

    @staticmethod
    def from_file(filename, human_readable=False, must_exist=False):
        try:
            if human_readable:
                retval = DictList()
                with open(filename, 'r') as f:
                    for line in f:
                        (key, val) = line.split(' ', 1)
                        retval[key] = list(map(lambda x: x.rstrip('\n'), val.split(' ')))
                    f.close()
                return retval
            else:
                with open(filename, 'rb') as f:
                    return DictList(pickle.load(f))

        except FileNotFoundError:
            print('Warning, file ' + filename + ' not found!')
            if must_exist:
                raise
            return DictList()


def preevaluate_single_patch(original_hash, candidate_hash):
    orig = get_commit(original_hash)
    cand = get_commit(candidate_hash)

    # We do not need to evaluate equivalent commit hashes, as they are already belong to the same equivalence class
    if original_hash == candidate_hash:
        return False

    # Don't rely on author dates!
    #delta = cand.author_date - orig.author_date
    #if delta.days < 0:
    #    return False

    # Check if patch is a revertion
    if orig.is_revert != cand.is_revert:
        return False

    # Filtert auch merge commits
    common_changed_files = len(orig.diff.affected.intersection(cand.diff.affected))
    if common_changed_files == 0:
        return False

    return True


def evaluate_single_patch(thresholds, original_hash, candidate_hash):

    # Just in case.
    # Actually, patches with the same commit hashes should never be compares, as preevaluate_single_patch will evaluate
    # to False for equivalent commit hashes.
    if original_hash == candidate_hash:
        print('Autoreturning on %s' % original_hash)
        return SimRating(1, 1, 1)

    orig = get_commit(original_hash)
    cand = get_commit(candidate_hash)

    left_diff_lines = orig.diff.lines
    right_diff_lines = cand.diff.lines

    diff_lines_ratio = min(left_diff_lines, right_diff_lines) / max(left_diff_lines, right_diff_lines)

    # get rating of message
    msg_rating = fuzz.token_sort_ratio(orig.message, cand.message) / 100

    # Skip on diff_lines_ratio less than 1%
    if diff_lines_ratio < 0.01:
        return SimRating(msg_rating, 0, diff_lines_ratio)

    # traverse through the left patch
    levenshteins = []
    for file_identifier, lhunks in orig.diff.patches.items():
        if file_identifier in cand.diff.patches:
            levenshtein = []
            rhunks = cand.diff.patches[file_identifier]

            for l_key, (l_removed, l_added) in lhunks.items():
                """
                 When comparing hunks, it is important to use the 'closest hunk' of the right side.
                 The left hunk does not necessarily have to be absolutely similar to the name of the right hunk.
                """

                r_key = None
                if l_key == '':
                    if '' in rhunks:
                        r_key = ''
                else:
                    # This gets the closed levenshtein rating from key against a list of candidate keys
                    closest_match, rating = sorted(
                            map(lambda x: (x, fuzz.token_sort_ratio(l_key, x)),
                                rhunks.keys()),
                            key=lambda x: x[1])[-1]
                    if rating >= thresholds.heading * 100:
                        r_key = closest_match

                if r_key is not None:
                    r_removed, r_added = rhunks[r_key]
                    if l_removed and r_removed:
                        levenshtein.append(fuzz.token_sort_ratio(l_removed, r_removed))
                    if l_added and r_added:
                        levenshtein.append(fuzz.token_sort_ratio(l_added, r_added))

            if levenshtein:
                levenshteins.append(mean(levenshtein))

    if not levenshteins:
        levenshteins = [0]

    diff_rating = mean(levenshteins) / 100

    return SimRating(msg_rating, diff_rating, diff_lines_ratio)


def _preevaluation_helper(candidate_hashes, orig_hash):
    f = functools.partial(preevaluate_single_patch, orig_hash)
    return orig_hash, list(filter(f, candidate_hashes))


def _evaluation_helper(thresholds, orig_cands, verbose=False):
    orig, cands = orig_cands
    if verbose:
        print('Evaluating 1 commit hash against %d commit hashes' % len(cands))

    f = functools.partial(evaluate_single_patch, thresholds, orig)
    results = list(map(f, cands))
    results = list(zip(cands, results))

    # sort SimRating
    results.sort(key=lambda x: x[1], reverse=True)

    return orig, results


def evaluate_patch_list(original_hashes, candidate_hashes, eval_type, thresholds,
                        parallelise=False, verbose=False,
                        cpu_factor=1.25):
    """
    Evaluates two list of original and candidate hashes against each other

    :param original_hashes: list of commit hashes
    :param candidate_hashes: list of commit hashes to compare against
    :param parallelise: Parallelise evaluation
    :param verbose: Verbose output
    :param cpu_factor: number of threads to be spawned is the number of CPUs*cpu_factor
    :return: a dictionary with originals as keys and a list of potential candidates as value
    """

    poolsize = int(cpu_count() * cpu_factor)

    print('Evaluating %d commit hashes against %d commit hashes' % (len(original_hashes), len(candidate_hashes)))

    # Bind candidate hashes to preevaluation
    f_preeval = functools.partial(_preevaluation_helper, candidate_hashes)
    # Bind thresholds to evaluation
    f_eval = functools.partial(_evaluation_helper, thresholds, verbose=True)

    if verbose:
        print('Running preevaluation.')
    if parallelise:
        p = Pool(poolsize)
        preeval_result = p.map(f_preeval, original_hashes)
    else:
        preeval_result = list(map(f_preeval, original_hashes))

    # Filter empty candidates
    preeval_result = dict(filter(lambda x: not not x[1], preeval_result))
    if verbose:
        print('Preevaluation finished.')

    if parallelise:
        result = p.map(f_eval, preeval_result.items())
        p.close()
        p.join()
    else:
        result = list(map(f_eval, preeval_result.items()))

    retval = EvaluationResult(eval_type=eval_type)
    for orig, evaluation in result:
        retval[orig] = evaluation

    return retval


def getch():
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(sys.stdin.fileno())
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    return ch


def compare_hashes(orig_commit_hash, cand_commit_hash):
    call(['./compare_hashes.sh', config.repo_location, orig_commit_hash, cand_commit_hash])
