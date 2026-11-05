"""Small, real classifiers. No training data or vocabulary is fit on test text."""
import hashlib
import json
from time import perf_counter

import sklearn
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix
from threadpoolctl import threadpool_limits

from .content import POSTS, REFERENCE

CONFIGURATIONS = {
    'word': {'name': 'Word features · balanced', 'analyzer': 'word', 'ngram_range': (1, 1), 'class_weight': 'balanced', 'multiplier': 1},
    'word_unweighted': {'name': 'Word features · observed proportions', 'analyzer': 'word', 'ngram_range': (1, 1), 'class_weight': None, 'multiplier': 1},
    'bigram': {'name': 'Words + word pairs · balanced', 'analyzer': 'word', 'ngram_range': (1, 2), 'class_weight': 'balanced', 'multiplier': 1.5},
    'character': {'name': 'Character fragments · balanced', 'analyzer': 'char_wb', 'ngram_range': (3, 5), 'class_weight': 'balanced', 'multiplier': 3},
}


def fingerprint(rows, configuration):
    return hashlib.sha256(json.dumps([configuration, rows], sort_keys=True).encode()).hexdigest()


def readiness(rows):
    if len(rows) < 6:
        return 'Need at least 6 distinct usable posts. Label more posts or audit tied votes.'
    counts = {label: sum(row['label'] == label for row in rows) for label in ('allow', 'remove')}
    if min(counts.values()) < 2:
        return 'Need at least 2 Allow and 2 Remove posts after majority voting. A single-class dataset cannot train this classifier.'
    return None


def fit_and_evaluate(rows, configuration):
    """Each distinct post gets one vote after aggregation; repeated labor is not oversampled."""
    problem = readiness(rows)
    if problem:
        raise ValueError(problem)
    if any(row['post_id'] not in range(100) for row in rows):
        raise ValueError('Held-out posts must never be included in training.')
    settings = CONFIGURATIONS[configuration]
    vectorizer = TfidfVectorizer(analyzer=settings['analyzer'], ngram_range=settings['ngram_range'], max_features=5000, sublinear_tf=True)
    classifier = LogisticRegression(class_weight=settings['class_weight'], solver='liblinear', max_iter=500, random_state=42)
    with threadpool_limits(limits=1):
        started = perf_counter()
        features = vectorizer.fit_transform([POSTS[row['post_id']] for row in rows])
        classifier.fit(features, [row['label'] for row in rows])
        training_ms = (perf_counter() - started) * 1000
        test_features = vectorizer.transform(POSTS[100:])
        predictions = classifier.predict(test_features)
        probabilities = classifier.predict_proba(test_features)
    target = [label for label, _ in REFERENCE]
    warnings = ['Small classroom dataset: scores are descriptive, not evidence of deployment readiness.',
                'Probabilities are uncalibrated model scores, not certainty or probabilities of moral correctness.']
    minority = min(sum(r['label'] == label for r in rows) for label in ('allow', 'remove'))
    if minority < 5:
        warnings.append('Fewer than 5 examples in the minority class; results may be unstable.')
    if configuration == 'word_unweighted':
        warnings.append('This configuration follows observed class proportions, which may favor the majority label.')
    result = {
        'accuracy': float(accuracy_score(target, predictions)),
        'confusion_matrix': confusion_matrix(target, predictions, labels=['allow', 'remove']).tolist(),
        'matrix_labels': ['allow', 'remove'], 'test_count': len(target),
        'reference_version': 'Common Ground policy reference v1', 'warnings': warnings,
        'predictions': [{'post_id': 100+i, 'prediction': str(predictions[i]),
                         'confidence': float(max(probabilities[i])),
                         'remove_score': float(probabilities[i][list(classifier.classes_).index('remove')]),
                         'no_known_features': test_features[i].nnz == 0} for i in range(len(target))],
    }
    # JSON only; no pickle loading. Retain learned parameters for reproducibility.
    artifact = {'sklearn_version': sklearn.__version__, 'vocabulary': {k:int(v) for k,v in vectorizer.vocabulary_.items()},
                'idf': vectorizer.idf_.tolist(), 'coefficients': classifier.coef_.tolist(),
                'intercept': classifier.intercept_.tolist(), 'classes': classifier.classes_.tolist()}
    return training_ms, result, artifact
