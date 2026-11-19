function reply(r) {
    setTimeout(() => {
        r.headersOut['Content-Type'] = 'application/json';
        r.return(200, '{"status": "slow", "endpoint": "slow", "message": "This is a deliberately slow response", "delay": "5000ms"}');
    }, 5000);
}

export default { reply };
