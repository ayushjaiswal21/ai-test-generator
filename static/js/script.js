async function generateQuiz() {
    const topics = document.getElementById('topics').value.split(',').map(t => t.trim());
    const qType = document.getElementById('q_type').value;
    const difficulty = document.getElementById('difficulty').value;
    const numQuestions = document.getElementById('num_questions').value;

    if (!topics.length || !qType || !difficulty || !numQuestions) {
        displayError("All fields are required!");
        return;
    }
    if (numQuestions < 1 || numQuestions > 20) {
        displayError("Please choose between 1 and 20 questions!");
        return;
    }

    try {
        const container = document.getElementById('quizContainer');
        container.innerHTML = "<p>Loading quiz...</p>";

        const response = await fetch("http://localhost:5000/api/generate-quiz", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                topics: topics,
                type: qType,
                difficulty: difficulty,
                num_questions: Number(numQuestions),
            }),
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || "Request failed");
        }

        if (!data.questions || data.questions.length === 0) {
            throw new Error("No questions generated");
        }

        displayQuiz(data.questions);

    } catch (error) {
        displayError(`Failed to generate quiz: ${error.message}`);
    }
}

function displayQuiz(questions) {
    const container = document.getElementById('quizContainer');
    container.innerHTML = questions.map((q, i) => `
        <div class="question">
            <h3>Q${i + 1}:</h3>
            <p>${q.text || q}</p>
        </div>
    `).join('');
}

function displayError(message) {
    const errorContainer = document.getElementById('errorContainer') || document.createElement('div');
    errorContainer.id = 'errorContainer';
    errorContainer.style.color = 'red';
    errorContainer.style.marginBottom = '1rem';
    errorContainer.textContent = message;
    if (!document.body.contains(errorContainer)) {
        document.body.prepend(errorContainer);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const generateBtn = document.getElementById('generateBtn');
    if (generateBtn) {
        generateBtn.addEventListener('click', generateQuiz);
    }
});
