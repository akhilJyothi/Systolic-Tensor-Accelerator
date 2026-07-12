module booth_multiplier #(
    parameter DATA_WIDTH = 8
)(
    input  logic signed [DATA_WIDTH-1:0] multiplicand,
    input  logic signed [DATA_WIDTH-1:0] multiplier,

    output logic signed [(2*DATA_WIDTH)-1:0] product
);
    localparam NUM_GROUPS = DATA_WIDTH/2;
    // Booth operation from each encoder
    logic [2:0] booth_op [0:NUM_GROUPS-1];

    // Partial products
    logic signed [(2*DATA_WIDTH)-1:0] partial_product [0:NUM_GROUPS-1];

    // Shifted partial products
    logic signed [(2*DATA_WIDTH)-1:0] shifted_pp [0:NUM_GROUPS-1];

    genvar i;

    generate

        for(i=0;i<NUM_GROUPS;i=i+1)
        begin : BOOTH_STAGE

            logic [2:0] booth_bits;
            if(i==0)
            begin

                assign booth_bits = {
                                    multiplier[1],
                                    multiplier[0],
                                    1'b0
                                    };

            end
            else
            begin

                assign booth_bits = {
                                    multiplier[(2*i)+1],
                                    multiplier[(2*i)],
                                    multiplier[(2*i)-1]
                                    };

            end

            // -----------------------------
            // Booth Encoder
            // -----------------------------

            booth_encoder encoder(

                .booth_bits(booth_bits),
                .booth_op(booth_op[i])

            );

            // -----------------------------
            // Partial Product Generator
            // -----------------------------

            partial_product_generator #(

                .DATA_WIDTH(DATA_WIDTH)

            ) pp_gen (

                .booth_op(booth_op[i]),
                .multiplicand(multiplicand),
                .partial_product(partial_product[i])

            );

            // -----------------------------
            // Shift partial product
            // -----------------------------

            assign shifted_pp[i] = partial_product[i] <<< (2*i);

        end
    endgenerate
    integer k;

    always_comb
    begin

        product = '0;

        for(k=0;k<NUM_GROUPS;k=k+1)
            product = product + shifted_pp[k];

    end

endmodule