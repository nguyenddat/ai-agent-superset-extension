import math
import re
import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

_WORD = re.compile(r"[^\W_]+")

def text_words(text: str) -> list[str]:
    return _WORD.findall(unicodedata.normalize("NFC", text).casefold())


def tfidf_vectors(texts: Sequence[str]) -> list[dict[str, float]]:
    counts = [Counter(text_words(text)) for text in texts]
    document_frequency = Counter(feature for count in counts for feature in count)
    total = len(texts)
    vectors = []
    for count in counts:
        weights = {
            feature: (1 + math.log(occurrences)) * (math.log((1 + total) / (1 + document_frequency[feature])) + 1)
            for feature, occurrences in count.items()
        }
        vectors.append(unit_vector(weights))
    return vectors


def unit_vector(vector: Any) -> Any:
    """A dense list or a sparse feature → weight map scaled to length 1; a zero vector stays as it is."""
    values = vector.values() if isinstance(vector, dict) else vector
    length = math.sqrt(sum(value * value for value in values))
    if not length:
        return vector
    if isinstance(vector, dict):
        return {feature: value / length for feature, value in vector.items()}
    return [value / length for value in vector]


def cosine(left: Any, right: Any) -> float:
    """The cosine similarity of two unit vectors, both dense lists or both sparse maps."""
    if isinstance(left, dict):
        smaller, larger = (left, right) if len(left) <= len(right) else (right, left)
        return sum(value * larger.get(feature, 0.0) for feature, value in smaller.items())
    return sum(left_value * right_value for left_value, right_value in zip(left, right))


def similarity_matrix(vectors: Sequence[Any]) -> list[list[float]]:
    """Pairwise cosine similarities of the vectors, after scaling each to unit length."""
    units = [unit_vector(vector) for vector in vectors]
    matrix = [[1.0] * len(units) for _ in units]
    for row in range(len(units)):
        for column in range(row + 1, len(units)):
            matrix[row][column] = matrix[column][row] = cosine(units[row], units[column])
    return matrix


@dataclass(frozen=True)
class NeighbourCluster:
    """Members close enough to be grouped: `member_indexes` are ungrouped members to put together, in the existing
    group `group_id` (whose members are `anchor_indexes`) or, when `group_id` is None, in a new group."""

    group_id: int | None
    member_indexes: tuple[int, ...]
    anchor_indexes: tuple[int, ...]


def neighbour_clusters(
    group_ids: Sequence[int | None], similarity: Sequence[Sequence[float]], threshold: float
) -> list[NeighbourCluster]:
    """Average-linkage agglomerative clustering of members that keeps the groups administrators already made.

    `group_ids[i]` is member i's group, or None. Each existing group starts as one fixed cluster and each ungrouped
    member as its own cluster. The two clusters with the highest average pairwise similarity merge while that average
    reaches `threshold`, except that two existing groups never merge: grouping is the administrators' decision, and a
    suggestion only places ungrouped members. Average linkage, unlike connected components, does not chain A to C
    through a B that is merely close to both.
    """
    clusters: dict[int, list[int]] = {}
    fixed_group: dict[int, int | None] = {}
    group_keys: dict[int, int] = {}
    for index, group_id in enumerate(group_ids):
        if group_id is None:
            key = len(clusters)
            clusters[key], fixed_group[key] = [index], None
        elif group_id in group_keys:
            clusters[group_keys[group_id]].append(index)
        else:
            key = group_keys[group_id] = len(clusters)
            clusters[key], fixed_group[key] = [index], group_id

    def pair(first: int, second: int) -> tuple[int, int]:
        return (first, second) if first < second else (second, first)

    def linkage(cluster_pair: tuple[int, int]) -> float:
        first, second = cluster_pair
        return sums[cluster_pair] / (len(clusters[first]) * len(clusters[second]))

    def close(cluster_pair: tuple[int, int]) -> bool:
        """Whether two clusters may merge: not two existing groups, and similar enough on average."""
        first, second = cluster_pair
        mergeable = fixed_group[first] is None or fixed_group[second] is None
        return mergeable and linkage(cluster_pair) >= threshold

    def rank(cluster_pair: tuple[int, int]) -> tuple[float, int, int]:
        # The lowest keys win a tie, so the same input always gives the same clusters.
        return linkage(cluster_pair), -cluster_pair[0], -cluster_pair[1]

    keys = list(clusters)
    sums = {
        (first, second): sum(similarity[row][column] for row in clusters[first] for column in clusters[second])
        for position, first in enumerate(keys)
        for second in keys[position + 1:]
    }
    candidates = {cluster_pair for cluster_pair in sums if close(cluster_pair)}
    next_key = len(clusters)
    while candidates:
        first, second = max(candidates, key=rank)
        merged, next_key = next_key, next_key + 1
        clusters[merged] = clusters.pop(first) + clusters.pop(second)
        fixed_group[merged] = fixed_group[first] if fixed_group[first] is not None else fixed_group[second]
        del sums[(first, second)]
        for other in clusters:
            if other != merged:
                sums[pair(other, merged)] = sums.pop(pair(other, first)) + sums.pop(pair(other, second))
        candidates = {cluster_pair for cluster_pair in candidates if not {first, second} & set(cluster_pair)}
        candidates.update(pair(other, merged) for other in clusters if other != merged and close(pair(other, merged)))

    result = []
    for key, indexes in clusters.items():
        group_id = fixed_group[key]
        moving = tuple(sorted(index for index in indexes if group_ids[index] is None))
        anchors = tuple(sorted(index for index in indexes if group_ids[index] is not None))
        if moving and (group_id is not None or len(moving) > 1):
            result.append(NeighbourCluster(group_id, moving, anchors))
    return result
