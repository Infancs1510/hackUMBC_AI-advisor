const test_id = "CID-834634";

document.getElementById("header-campus-id").textContent = test_id;

const chatInput = document.querySelector("#chat-input");
const sendButton = document.querySelector("#send-message");

fetch("data/students_current.csv")
    .then(response => {
        if (!response.ok) throw new Error("Unable to load current students.");
        return response.text();
    })
    .then(data => {

        const student = findStudent(data, test_id);
        if (!student) throw new Error("No current student matches " + test_id + ".");
        const gpa = Number(student.cumulativeGpa);
        document.getElementById("welcome-gpa").textContent =
            student.cumulativeGpa && Number.isFinite(gpa) ? gpa.toFixed(2) : "Not available";
        document.getElementById("welcome-class-standing").textContent = student.classLevel || "Not available";

        return loadAlumniData(student)
            .then(salary => {

                const salaryToCost = CalculateROI(student, salary);

                displayROI(student, salaryToCost);
            });

    })
    .catch(error => {
        CareerPaths.showError(error.message);
        console.error(error);
    });

    function findStudent(data, student_id) {

        const trimmed_data =  data.trim().split("\n");

        for (const row of trimmed_data) {

            const columns = row.split(",");

            if (columns[0] === student_id) {

                const student = {
                    major: columns[3],
                    track: columns[4],
                    classLevel: columns[7],
                    cumulativeGpa: columns[14],
                    residency: columns[8],
                    creditsEarned: columns[12],
                    creditsRequired: columns[13],
                    expectedGraduation: columns[17],
                    tuitionPaid: columns[21],
                    entryDate: columns[1]
                };

                return student;
            }

        }
    } 

    function displayROI(student, ROI) {

        //Tuition
        const tuition = Number(student.tuitionPaid);

       document.querySelector("#tuition").textContent = "$" + tuition.toLocaleString();
        
        //Major and Track
        document.querySelector("#degree").textContent = student.major;
        document.querySelector("#track").textContent = student.track;

        //Years to Complete

        const graduation = student.expectedGraduation;
        const gradParts = graduation.split(" ");
        
        const entry = student.entryDate;
        const entryParts = entry.split(" ");

        const years = Number(gradParts[1]) - Number(entryParts[1]);

        document.querySelector("#years").textContent = years + " Years";

        //SalaryToCost
        document.querySelector("#estimated-roi").textContent = ROI.toFixed(2) + "x";


    }

    function loadAlumniData(student) {

        return fetch("data/alumni.csv")
            .then(response => {
                if (!response.ok) throw new Error("Unable to load alumni outcomes.");
                return response.text();
            })
            .then(data => {
                CareerPaths.render(data, student);

                const salary = estimateSalary(data, student);

                document.querySelector("#estimated-salary").textContent =
                    "$" + salary.toLocaleString();

                return salary;
            });
    }


    function estimateSalary(data, student) {

        const rows = data.trim().split("\n");

        let totalSalary = 0;
        let salaryCount = 0;

        for (let i = 1; i < rows.length; i++) {

            const columns = rows[i].split(",");

            const major = columns[1];
            const track = columns[3];

            // Because some later fields contain commas,
            // salary position can shift, so grab it from near the end
            const salary = columns[columns.length - 3];

            if (
                major === student.major &&
                track === student.track &&
                salary !== "Not Applicable"
            ) {
                totalSalary += Number(salary);
                salaryCount++;
            }
        }

        if (salaryCount === 0) {
            return 0;
        }

        return Math.round(totalSalary / salaryCount);
    }

    function CalculateROI(student, salary) {

        const annualInState = 13000;
        const annualOutState = 35000;

        const tuitionPaid = Number(student.tuitionPaid);

        // Figure out estimated annual tuition
        let annualTuition;

        if (student.residency === "In-State") {
            annualTuition = annualInState;
        } else {
            annualTuition = annualOutState;
        }

        // Calculate years remaining
        const graduationParts = student.expectedGraduation.split(" ");
        const graduationYear = Number(graduationParts[1]);

        const currentYear = 2026;

        const yearsRemaining = graduationYear - currentYear;

        // Estimate final tuition cost
        const estimatedTotalCost =
            tuitionPaid + (annualTuition * yearsRemaining);

        // Salary-to-cost ratio
        const salaryToCost =
            salary / estimatedTotalCost;

        return salaryToCost;
    }

    sendButton.addEventListener("click", sendMessage);

    chatInput.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
            sendMessage();
        }
    });

    function addMessage(role, text) {
        const messageEl = document.createElement("div");
        messageEl.className = role === "user" ? "user-message" : "bot-message";

        const paragraph = document.createElement("p");
        paragraph.textContent = text;
        messageEl.appendChild(paragraph);

        const chatMessages = document.querySelector(".chat-messages");
        chatMessages.appendChild(messageEl);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    function sendMessage() {

        const message = chatInput.value.trim();

        if (!message) {
            return;
        }

        addMessage("user", message);
        chatInput.value = "";

        fetch("http://127.0.0.1:8000/api/advisor", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                campus_id: test_id,
                message: message
            })
        })
        .then(async response => {
            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.detail || "Request failed");
            }
            return data;
        })
        .then(data => {
            addMessage("bot", data.reply || "I’m not sure how to answer that yet.");
        })
        .catch(error => {
            addMessage("bot", "I couldn’t reach the advisor service right now. Please try again in a moment.");
            console.error(error);
        });
    }
