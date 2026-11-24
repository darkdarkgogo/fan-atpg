"""Dynamic fault features and the shared actor-critic network."""

import time

import torch
from torch import nn


def build_dynamic_features(embeddings, remaining_rows):
    """Combine candidate embeddings with their current remaining-set context."""
    if embeddings.ndim != 2 or embeddings.shape[0] == 0 or embeddings.shape[1] != 257:
        raise ValueError("embeddings must have shape [N, 257] with N > 0")
    if not torch.isfinite(embeddings).all():
        raise ValueError("embeddings contain non-finite values")
    rows = torch.as_tensor(remaining_rows, device=embeddings.device)
    if rows.ndim != 1 or rows.numel() == 0:
        raise ValueError("remaining rows must be a non-empty one-dimensional sequence")
    if rows.dtype not in (torch.uint8, torch.int8, torch.int16, torch.int32, torch.int64):
        raise ValueError("remaining rows must contain integer indices")
    if (rows < 0).any() or (rows >= embeddings.shape[0]).any():
        raise ValueError("remaining rows contain an out-of-range index")
    if torch.unique(rows).numel() != rows.numel():
        raise ValueError("remaining rows must be unique")
    candidates = embeddings[rows.long()]
    context = candidates.mean(dim=0, keepdim=True).expand(rows.numel(), -1)
    ratio = embeddings.new_full((rows.numel(), 1), rows.numel() / embeddings.shape[0])
    return torch.cat((candidates, context, ratio), dim=1)


class FaultActorCritic(nn.Module):
    def __init__(self):
        super().__init__()
        self.input_dimension = 515
        self.encoder = nn.Sequential(
            nn.LayerNorm(self.input_dimension),
            nn.Linear(self.input_dimension, 256),
            nn.ReLU(),
            nn.Linear(256, 128),
            nn.ReLU(),
        )
        self.actor_head = nn.Linear(128, 1)
        self.critic_head = nn.Sequential(
            nn.Linear(128, 64),
            nn.ReLU(),
            nn.Linear(64, 1),
        )

    def forward(self, features):
        if features.ndim != 2 or features.shape[1] != self.input_dimension:
            raise ValueError(
                "fault features must have shape [N, {}]".format(
                    self.input_dimension
                )
            )
        if not torch.isfinite(features).all():
            raise ValueError("fault features contain non-finite values")
        encoded = self.encoder(features)
        scores = self.actor_head(encoded).squeeze(-1)
        value = self.critic_head(encoded.mean(dim=0)).squeeze(-1)
        if not torch.isfinite(scores).all() or not torch.isfinite(value):
            raise ValueError("fault actor-critic produced non-finite outputs")
        return scores, value


# Source compatibility for callers which import the historical class name.
FaultScorer = FaultActorCritic


@torch.no_grad()
def score_remaining(model, embeddings, remaining_rows, chunk_size=16384,
                    timings=None):
    """Bound inference activations while retaining complete-set context/value.

    The context is computed over ALL remaining rows, not each chunk. LayerNorm
    and the MLP act independently on rows; the critic uses their global mean.
    This function is for rollout/evaluation only; PPO replay retains gradients.
    """
    from .runtime import synchronize

    if isinstance(chunk_size, bool) or not isinstance(chunk_size, int) or chunk_size <= 0:
        raise ValueError("inference chunk size must be a positive integer")
    device = embeddings.device
    synchronize(device)
    started = time.perf_counter()
    rows = torch.as_tensor(remaining_rows, device=device, dtype=torch.long)
    if (rows.ndim != 1 or rows.numel() == 0 or embeddings.ndim != 2
            or embeddings.shape[1] != 257 or (rows < 0).any()
            or (rows >= embeddings.shape[0]).any()
            or torch.unique(rows).numel() != rows.numel()):
        raise ValueError("invalid remaining rows or embeddings")
    count = rows.numel()
    if count <= chunk_size:
        features = build_dynamic_features(embeddings, rows)
        synchronize(device)
        feature_s = time.perf_counter() - started
        forward_started = time.perf_counter()
        scores, value = model(features)
        synchronize(device)
        forward_s = time.perf_counter() - forward_started
    else:
        context = embeddings.new_zeros(257)
        for part in rows.split(chunk_size):
            context += embeddings[part].sum(0)
        context /= count
        synchronize(device)
        feature_s = time.perf_counter() - started
        forward_s = 0.0
        score_parts = []
        encoded_sum = embeddings.new_zeros(128)
        for part in rows.split(chunk_size):
            started = time.perf_counter()
            features = torch.cat((embeddings[part], context.expand(part.numel(), -1),
                                  embeddings.new_full((part.numel(), 1), count / embeddings.shape[0])), dim=1)
            if not torch.isfinite(features).all():
                raise ValueError("fault features contain non-finite values")
            synchronize(device)
            feature_s += time.perf_counter() - started
            started = time.perf_counter()
            encoded = model.encoder(features)
            score_parts.append(model.actor_head(encoded).squeeze(-1))
            encoded_sum += encoded.sum(0)
            synchronize(device)
            forward_s += time.perf_counter() - started
        started = time.perf_counter()
        scores = torch.cat(score_parts)
        value = model.critic_head(encoded_sum / count).squeeze(-1)
        synchronize(device)
        forward_s += time.perf_counter() - started
        if not torch.isfinite(scores).all() or not torch.isfinite(value):
            raise ValueError("fault actor-critic produced non-finite outputs")
    if timings is not None:
        timings.update(features_s=feature_s, forward_s=forward_s)
    return scores, value
