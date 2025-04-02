async function generateQuiz() {
    // Get user inputs
    const topics = document.getElementById('topics').value.split(',').map(t => t.trim()).filter(t => t !== '');
    const qType = document.getElementById('q_type').value;
    const difficulty = document.getElementById('difficulty').value;
    const numQuestions = document.getElementById('num_questions').value;

    // Validate inputs
    if (topics.length === 0 || !qType || !difficulty || !numQuestions) {
        displayError("All fields are required!");
        return;
    }
    
    const num = Number(numQuestions);
    if (isNaN(num) || num < 1 || num > 20) {
        displayError("Please choose between 1 and 20 questions!");
        return;
    }

    try {
        // Show loading message while fetching quiz
        const container = document.getElementById('quizContainer');
        container.innerHTML = "<p>Loading quiz...</p>";

        // Clear previous errors
        clearError();

        // Send POST request to the backend API
        const response = await fetch("/api/generate-quiz", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                topics: topics,
                type: qType,
                difficulty: difficulty,
                num_questions: num,
            }),
        });

        // Parse response data
        const data = await response.json();

        // Check for errors first
        if (!response.ok) {
            throw new Error(data.error || `Request failed with status ${response.status}`);
        }

        if (response.status === 207) {
            // Questions generated but not saved to database
            console.warn("Database warning:", data.warning);
            displayQuiz(data.questions, qType);
            return;
        }

        if (!data.questions || data.questions.length === 0) {
            throw new Error("No questions generated");
        }

        // Display the generated quiz
        displayQuiz(data.questions, qType);

    } catch (error) {
        // Handle errors gracefully
        displayError(`Failed to generate quiz: ${error.message}`);
        console.error("Quiz generation error:", error);
    }
}

function displayQuiz(questions, questionType) {
    const container = document.getElementById('quizContainer');
    
    if (questions.length === 0) {
        container.innerHTML = "<p>No questions to display</p>";
        return;
    }

    let quizHTML = '';
    
    questions.forEach((q, i) => {
        const questionText = q.question ? escapeHTML(q.question) : "Invalid question format";
        const answerText = q.answer ? escapeHTML(q.answer) : "No answer provided";
        
        let optionsHTML = '';
        let isMultipleChoice = false;
        let questionContent = questionText;
        
        // Check for multiple choice pattern (A), B), etc.)
        const optionRegex = /([A-Da-d]\))\s*(.+?)(?=\s+[A-Da-d]\)|$)/g;
        let match;
        const options = [];
        
        while ((match = optionRegex.exec(questionText)) !== null) {
            options.push({
                letter: match[1].charAt(0).toUpperCase(),
                text: match[2].trim()
            });
            // Remove the option from the main question text
            questionContent = questionContent.replace(match[0], '');
        }
        
        if (options.length > 0) {
            isMultipleChoice = true;
            options.forEach(opt => {
                optionsHTML += `
                    <div class="option">
                        <input type="radio" name="question_${i}" id="q${i}_opt${opt.letter}" value="${opt.letter}">
                        <label for="q${i}_opt${opt.letter}">${opt.letter}) ${opt.text}</label>
                    </div>
                `;
            });
        }
        
        quizHTML += `
            <div class="question" data-answer="${answerText.trim().toUpperCase()}" data-index="${i}">
                <h3>Question ${i + 1}:</h3>
                <div class="question-text">${questionContent}</div>
                
                ${isMultipleChoice ? `
                    <div class="options">
                        ${optionsHTML}
                    </div>
                    <button class="confirm-btn" onclick="checkAnswer(${i})">Check Answer</button>
                    <div id="result_${i}" class="result hidden"></div>
                ` : `
                    <details class="answer-details">
                        <summary>Show Answer</summary>
                        <div class="answer-text">${answerText}</div>
                    </details>
                `}
            </div>
        `;
    });
    
    container.innerHTML = quizHTML;
}

function checkAnswer(questionIndex) {
    const questionDiv = document.querySelector(`.question[data-index="${questionIndex}"]`);
    const selectedOption = document.querySelector(`input[name="question_${questionIndex}"]:checked`);
    const correctAnswer = questionDiv.getAttribute('data-answer');
    const resultDiv = document.getElementById(`result_${questionIndex}`);
    
    if (!selectedOption) {
        resultDiv.textContent = "Please select an answer first!";
        resultDiv.className = "result error";
        resultDiv.classList.remove("hidden");
        return;
    }
    
    const selectedValue = selectedOption.value.toUpperCase();
    resultDiv.classList.remove("hidden");
    
    if (selectedValue === correctAnswer.charAt(0)) {
        resultDiv.textContent = "✓ Correct!";
        resultDiv.className = "result correct";
    } else {
        resultDiv.textContent = `✗ Incorrect! The correct answer is ${correctAnswer}`;
        resultDiv.className = "result incorrect";
    }
    
    // Disable all radios after answering
    const radios = questionDiv.querySelectorAll('input[type="radio"]');
    radios.forEach(radio => {
        radio.disabled = true;
    });
}

// ... (keep the rest of your existing functions)

function checkAnswer(questionIndex) {
    const questionDiv = document.querySelector(`.question[data-index="${questionIndex}"]`);
    const selectedOption = document.querySelector(`input[name="question_${questionIndex}"]:checked`);
    const correctAnswer = questionDiv.getAttribute('data-answer');
    const resultDiv = document.getElementById(`result_${questionIndex}`);
    
    if (!selectedOption) {
        resultDiv.textContent = "Please select an answer first!";
        resultDiv.className = "result error";
        resultDiv.classList.remove("hidden");
        return;
    }
    
    const selectedValue = selectedOption.value.toUpperCase();
    resultDiv.classList.remove("hidden");
    
    // Compare answers (flexible comparison)
    const normalizedSelected = selectedValue.replace(/[).]/g, '').trim();
    const normalizedCorrect = correctAnswer.replace(/[).]/g, '').trim();
    
    if (normalizedSelected === normalizedCorrect) {
        resultDiv.textContent = "✓ Correct!";
        resultDiv.className = "result correct";
    } else {
        resultDiv.textContent = `✗ Incorrect! The correct answer is ${correctAnswer}`;
        resultDiv.className = "result incorrect";
    }
    
    // Disable all radios after answering
    const radios = questionDiv.querySelectorAll('input[type="radio"]');
    radios.forEach(radio => {
        radio.disabled = true;
    });
    
    // Disable confirm button
    const confirmBtn = questionDiv.querySelector('.confirm-btn');
    if (confirmBtn) {
        confirmBtn.disabled = true;
    }
}

// Helper function to escape HTML
function escapeHTML(str) {
    if (!str) return "";
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function displayError(message) {
    const errorContainer = document.getElementById('errorContainer');
    errorContainer.textContent = message;
    errorContainer.classList.remove("hidden");
}

function clearError() {
    const errorContainer = document.getElementById('errorContainer');
    errorContainer.textContent = "";
    errorContainer.classList.add("hidden");
}

document.addEventListener('DOMContentLoaded', () => {
    const generateBtn = document.getElementById('generateBtn');
    if (generateBtn) {
        generateBtn.addEventListener('click', generateQuiz);
    }

    // Optional: Add form submission handler
    const quizForm = document.querySelector('form');
    if (quizForm) {
        quizForm.addEventListener('submit', (e) => {
            e.preventDefault();
            generateQuiz();
        });
    }
});