CREATE TABLE IF NOT EXISTS recommendation_generations (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    type VARCHAR(20) NOT NULL
);

CREATE TABLE IF NOT EXISTS recommendation_items (
    generation_id BIGINT NOT NULL,
    movie_id BIGINT NOT NULL,
    score DOUBLE PRECISION NOT NULL,
    rank SMALLINT NOT NULL,

    PRIMARY KEY (generation_id, movie_id),

    CONSTRAINT fk_generation
        FOREIGN KEY (generation_id)
        REFERENCES recommendation_generations(id)
        ON DELETE CASCADE,

    CONSTRAINT valid_score
        CHECK (score >= 0 AND score <= 1),

    CONSTRAINT valid_rank
        CHECK (rank > 0)
);